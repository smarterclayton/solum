#    Copyright 2013 IBM Corp.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Solum common internal object model"""

import collections
import copy

import six

from solum.objects import fields
from solum.openstack.common.gettextutils import _
from solum.openstack.common import log as logging
from solum.openstack.common import versionutils


LOG = logging.getLogger('object')


class NotSpecifiedSentinel:
    pass


class ObjectException(Exception):
    """Base Object Exception."""


class UnsupportedObjectError(ObjectException):
    def __init__(self, **kwargs):
        super(ObjectException, self).__init__(
            _('Unsupported object type %(objtype)s') % kwargs
        )


class OrphanedObjectError(ObjectException):
    def __init__(self, **kwargs):
        super(ObjectException, self).__init__(
            _('Cannot call %(method)s on orphaned %(objtype)s object') % kwargs
        )


class IncompatibleObjectVersion(ObjectException):
    def __init__(self, **kwargs):
        super(ObjectException, self).__init__(
            _('Version %(objver)s of %(objname)s is not supported') % kwargs
        )


def get_attrname(name):
    """Return the mangled name of the attribute's underlying storage."""
    return '_%s' % name


def make_class_properties(cls):
    # NOTE(danms/comstud): Inherit fields from super classes.
    # mro() returns the current class first and returns 'object' last, so
    # those can be skipped.  Also be careful to not overwrite any fields
    # that already exist.  And make sure each cls has its own copy of
    # fields and that it is not sharing the dict with a super class.
    cls.fields = dict(cls.fields)
    for supercls in cls.mro()[1:-1]:
        if not hasattr(supercls, 'fields'):
            continue
        for name, field in supercls.fields.items():
            if name not in cls.fields:
                cls.fields[name] = field
    for name, field in cls.fields.iteritems():

        def getter(self, name=name):
            attrname = get_attrname(name)
            if not hasattr(self, attrname):
                self.obj_load_attr(name)
            return getattr(self, attrname)

        def setter(self, value, name=name, field=field):
            self._changed_fields.add(name)
            try:
                return setattr(self, get_attrname(name),
                               field.coerce(self, name, value))
            except Exception:
                attr = "%s.%s" % (self.obj_name(), name)
                LOG.exception(_('Error setting %(attr)s') %
                              {'attr': attr})
                raise

        setattr(cls, name, property(getter, setter))


def register_obj_class(cls):
    """Register this object class with the registry.

    The provided object must be a subclass of DomainObject.
    """
    if not issubclass(cls, AbstractDomainObject):
        raise UnsupportedObjectError(objtype=cls.__name__)

    if not hasattr(cls, '_obj_classes'):
        AbstractDomainObject._obj_classes = collections.defaultdict(list)

    if cls != DomainObject:
        cls._obj_classes[cls.obj_name()].append(cls)


def reset_obj_classes():
    """Clear all registered object classes."""
    AbstractDomainObject._obj_classes = collections.defaultdict(list)


def obj_class_for_name(name):
    """Return the first object class defined for the provided name."""
    return AbstractDomainObject._obj_classes[name][0]


class AbstractDomainObject(object):
    """Base class and object factory.

    This forms the base of all objects that can be remoted or instantiated
    via RPC. Simply defining a class that inherits from this base class
    will make it remotely instantiatable. Objects should implement the
    necessary "get" classmethod routines as well as "save" object methods
    as appropriate.
    """

    # Object versioning rules
    #
    # Each service has its set of objects, each with a version attached. When
    # a client attempts to call an object method, the server checks to see if
    # the version of that object matches (in a compatible way) its object
    # implementation. If so, cool, and if not, fail.
    VERSION = '1.0'

    # The fields present in this object as key:field pairs. For example:
    #
    # fields = { 'foo': fields.IntegerField(),
    #            'bar': fields.StringField(),
    #          }
    fields = {}
    obj_extra_fields = []

    def __init__(self, context=None, **kwargs):
        self._changed_fields = set()
        self._context = context
        for key in kwargs.keys():
            self[key] = kwargs[key]

    @classmethod
    def obj_name(cls):
        """Return a canonical name for this object which will be used over
        the wire for remote hydration.
        """
        return cls.__name__

    @classmethod
    def obj_class_from_name(cls, objname, objver):
        """Returns a class from the registry based on a name and version."""
        if objname not in cls._obj_classes:
            LOG.error(_('Unable to instantiate unregistered object type '
                        '%(objtype)s') % dict(objtype=objname))
            raise UnsupportedObjectError(objtype=objname)

        compatible_match = None
        for objclass in cls._obj_classes[objname]:
            if objclass.VERSION == objver:
                return objclass

            if versionutils.is_compatible(objver, objclass.VERSION):
                compatible_match = objclass

        if compatible_match:
            return compatible_match

        raise IncompatibleObjectVersion(objname=objname,
                                        objver=objver)

    @classmethod
    def obj_from_primitive(cls, primitive, context=None):
        """Object field-by-field hydration."""
        if primitive['domain_object.namespace'] != cls.namespace:
            # NOTE(danms): We don't do anything with this now, but it's
            # there for "the future"
            raise UnsupportedObjectError(
                objtype='%s.%s' % (primitive['domain_object.namespace'],
                                   primitive['domain_object.name']))
        objname = primitive['domain_object.name']
        objver = primitive['domain_object.version']
        objdata = primitive['domain_object.data']
        objclass = cls.obj_class_from_name(objname, objver)
        self = objclass()
        self._context = context
        for name, field in self.fields.items():
            if name in objdata:
                setattr(self, name, field.from_primitive(self, name,
                                                         objdata[name]))
        changes = primitive.get('domain_object.changes', [])
        self._changed_fields = set([x for x in changes if x in self.fields])
        return self

    def __deepcopy__(self, memo):
        """Efficiently make a deep copy of this object."""

        # NOTE(danms): A naive deepcopy would copy more than we need,
        # and since we have knowledge of the volatile bits of the
        # object, we can be smarter here. Also, nested entities within
        # some objects may be uncopyable, so we can avoid those sorts
        # of issues by copying only our field data.

        nobj = self.__class__()
        nobj._context = self._context
        for name in self.fields:
            if self.obj_attr_is_set(name):
                nval = copy.deepcopy(getattr(self, name), memo)
                setattr(nobj, name, nval)
        nobj._changed_fields = set(self._changed_fields)
        return nobj

    def obj_clone(self):
        """Create a copy."""
        return copy.deepcopy(self)

    def obj_make_compatible(self, primitive, target_version):
        """Make an object representation compatible with a target version.

        This is responsible for taking the primitive representation of
        an object and making it suitable for the given target_version.
        This may mean converting the format of object attributes, removing
        attributes that have been added since the target version, etc.

        :param:primitive: The result of self.obj_to_primitive()
        :param:target_version: The version string requested by the recipient
                               of the object.
        :param:raises: solum.objects.UnsupportedObjectError if conversion
                       is not possible for some reason.
        """
        pass

    def obj_to_primitive(self, target_version=None):
        """Simple base-case dehydration.

        This calls to_primitive() for each item in fields.
        """
        primitive = dict()
        for name, field in self.fields.items():
            if self.obj_attr_is_set(name):
                primitive[name] = field.to_primitive(self, name,
                                                     getattr(self, name))
        if target_version:
            self.obj_make_compatible(primitive, target_version)
        obj = {'domain_object.name': self.obj_name(),
               'domain_object.namespace': 'nova',
               'domain_object.version': target_version or self.VERSION,
               'domain_object.data': primitive}
        if self.obj_what_changed():
            obj['domain_object.changes'] = list(self.obj_what_changed())
        return obj

    def obj_load_attr(self, attrname):
        """Load an additional attribute from the real object.

        This should use self._conductor, and cache any data that might
        be useful for future load operations.
        """
        raise NotImplementedError(
            _("Cannot load '%s' in the base class") % attrname)

    def save(self, context):
        """Save the changed fields back to the store.

        This is optional for subclasses, but is presented here in the base
        class for consistency among those that do.
        """
        raise NotImplementedError('Cannot save anything in the base class')

    def obj_what_changed(self):
        """Returns a set of fields that have been modified."""
        return self._changed_fields

    def obj_get_changes(self):
        """Returns a dict of changed fields and their new values."""
        changes = {}
        for key in self.obj_what_changed():
            changes[key] = self[key]
        return changes

    def obj_reset_changes(self, fields=None):
        """Reset the list of fields that have been changed.

        Note that this is NOT "revert to previous values"
        """
        if fields:
            self._changed_fields -= set(fields)
        else:
            self._changed_fields.clear()

    def obj_attr_is_set(self, attrname):
        """Test object to see if attrname is present.

        Returns True if the named attribute has a value set, or
        False if not. Raises AttributeError if attrname is not
        a valid attribute for this object.
        """
        if attrname not in self.obj_fields:
            raise AttributeError(
                _("%(objname)s object has no attribute '%(attrname)s'") %
                {'objname': self.obj_name(), 'attrname': attrname})
        return hasattr(self, get_attrname(attrname))

    @property
    def obj_fields(self):
        return self.fields.keys() + self.obj_extra_fields


class DomainObjectMetaclass(type):
    """Metaclass that allows tracking of object classes.

    Classes that subclass AbstractDomainObject must invoke
    make_class_properties(cls) directly.
    """

    # Controls whether object operations are remoted. If this is
    # not None, use it to remote things over RPC.
    indirection_api = None

    def __init__(cls, name, bases, dict_):
        if name != 'AbstractDomainObject' and name != 'DomainObject':
            make_class_properties(cls)
            register_obj_class(cls)


@six.add_metaclass(DomainObjectMetaclass)
class DomainObject(AbstractDomainObject):
    """Base class for heirarchies with the default metaclass."""


class PersistentDomainObject(object):
    """Mixin class for Persistent objects.
    This adds the fields that we use in common for all persisent objects.
    """
    fields = {
        'created_at': fields.DateTimeField(nullable=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'deleted_at': fields.DateTimeField(nullable=True),
        'deleted': fields.BooleanField(default=False),
    }


class DomainObjectListBase(object):
    """Mixin class for lists of objects.

    This mixin class can be added as a base class for an object that
    is implementing a list of objects. It adds a single field of 'objects',
    which is the list store, and behaves like a list itself. It supports
    serialization of the list of objects automatically.
    """
    fields = {
        'objects': fields.ListOfObjectsField('DomainObject'),
    }

    def __iter__(self):
        """List iterator interface."""
        return iter(self.objects)

    def __len__(self):
        """List length."""
        return len(self.objects)

    def __getitem__(self, index):
        """List index access."""
        if isinstance(index, slice):
            new_obj = self.__class__()
            new_obj.objects = self.objects[index]
            # NOTE(danms): We must be mixed in with a DomainObject!
            new_obj.obj_reset_changes()
            new_obj._context = self._context
            return new_obj
        return self.objects[index]

    def __contains__(self, value):
        """List membership test."""
        return value in self.objects

    def count(self, value):
        """List count of value occurrences."""
        return self.objects.count(value)

    def index(self, value):
        """List index of value."""
        return self.objects.index(value)

    def _attr_objects_to_primitive(self):
        """Serialization of object list."""
        return [x.obj_to_primitive() for x in self.objects]

    def _attr_objects_from_primitive(self, value):
        """Deserialization of object list."""
        objects = []
        for entity in value:
            obj = DomainObject.obj_from_primitive(entity,
                                                  context=self._context)
            objects.append(obj)
        return objects


def obj_to_primitive(obj):
    """Recursively turn an object into a python primitive.

    A DomainObject becomes a dict, and anything that implements
    DomainObjectListBase becomes a list.
    """
    if isinstance(obj, DomainObjectListBase):
        return [obj_to_primitive(x) for x in obj]
    elif isinstance(obj, DomainObject):
        result = {}
        for key, value in obj.iteritems():
            result[key] = obj_to_primitive(value)
        return result
    else:
        return obj


def obj_make_list(context, list_obj, item_cls, db_list, **extra_args):
    """Construct an object list from a list of primitives.

    This calls item_cls._from_db_object() on each item of db_list, and
    adds the resulting object to list_obj.

    :param:context: Request contextr
    :param:list_obj: A DomainObjectListBase object
    :param:item_cls: The DomainObject class of the objects within the list
    :param:db_list: The list of primitives to convert to objects
    :param:extra_args: Extra arguments to pass to _from_db_object()
    :returns: list_obj
    """
    list_obj.objects = []
    for db_item in db_list:
        item = item_cls._from_db_object(context, item_cls(), db_item,
                                        **extra_args)
        list_obj.objects.append(item)
    list_obj._context = context
    list_obj.obj_reset_changes()
    return list_obj