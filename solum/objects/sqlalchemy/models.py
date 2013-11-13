# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
SQLAlchemy models for application data.
"""

import collections
import urlparse

from oslo.config import cfg

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.declarative import DeclarativeMeta

from solum import objects
from solum.objects import base
from solum.openstack.common.db import exception as db_exc
from solum.openstack.common.db.sqlalchemy import models
from solum.openstack.common.db.sqlalchemy import session as db_session


sql_opts = [
    cfg.StrOpt('mysql_engine',
               default='InnoDB',
               help='MySQL engine'),
]

cfg.CONF.register_opts(sql_opts, 'database')


def table_args():
    engine_name = urlparse.urlparse(cfg.CONF.database_connection).scheme
    if engine_name == 'mysql':
        return {'mysql_engine': cfg.CONF.mysql_engine,
                'mysql_charset': "utf8"}
    return None


def model_query(context, model, *args, **kwargs):
    """Query helper.

    :param context: context to query under
    :param session: if present, the session to use
    """

    session = kwargs.get('session') or db_session.get_session()
    query = session.query(model, *args)
    return query


class SolumBase(models.TimestampMixin,
                models.ModelBase):

    metadata = None

    @classmethod
    def obj_name(cls):
        return cls.__name__

    def as_dict(self):
        d = {}
        for c in self.__table__.columns:
            d[c.name] = self[c.name]
        return d

    @classmethod
    def get_by_id(cls, context, item_id):
        query = db_session.get_session().query(cls).filter_by(id=item_id)
        result = query.first()
        if not result:
            cls._not_found(item_id)
        return result

    def save(self, context):
        if objects.transition_schema():
            self.add_forward_schema_changes()

        session = db_session.get_session()
        with session.begin():
            session.merge(self)

        # updates = self.obj_get_changes()
        # updates.pop('id', None)

        # session = db_session.get_session()
        # with session.begin():
        #     query = session.query(self.__class__).filter_by(id=self.id)
        #     result = query.first()
        #     if not result:
        #         self._not_found(self.id)

        #     result.update(updates)

        # self.obj_reset_changes()

    def create(self, context):
        session = db_session.get_session()
        with session.begin():
            try:
                session.add(self)
            except db_exc.DBDuplicateEntry as e:
                self.__class__._duplicate_object(e, self)

        #self.obj_reset_changes()

    def destroy(self, context):
        session = db_session.get_session()
        with session.begin():
            session.query(self.__class__).\
                filter_by(id=self.id).\
                delete()


class DomainObjectMetaclass(DeclarativeMeta):
    """Metaclass that allows tracking of object classes."""

    indirection_api = None

    def __init__(cls, names, bases, dict_):
        DeclarativeMeta.__init__(cls, names, bases, dict_)
        if not hasattr(cls, '_obj_classes'):
            # This will be set in the 'DomainObject' class.
            cls._obj_classes = collections.defaultdict(list)
        else:
            # Add the subclass to DomainObject._obj_classes
            base.make_class_properties(cls)
            cls._obj_classes[cls.obj_name()].append(cls)


Base = declarative_base(cls=SolumBase)
