# Copyright 2013 - Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
test_objects
----------------------------------

Tests for solum 'objects' module
"""

from solum import objects
from solum.objects import base
from solum.openstack.common import test
from solum.tests import utils


class TestObjects(test.BaseTestCase):
    def setUp(self):
        super(test.BaseTestCase, self).setUp()
        utils.setup_dummy_db()
        utils.reset_dummy_db()
        self.ctx = utils.dummy_context()

    def tearDown(self):
        super(test.BaseTestCase, self).tearDown()

    def test_objects_registered(self):
        assert objects.registry.Application
        assert objects.registry.ApplicationList

    def test_objects_reloadable(self):
        assert objects.registry.Application

        self.addCleanup(objects.load)
        objects.registry.clear()

        self.assertRaises(AttributeError, lambda: base.registry.Application)

    def test_object_creatable(self):
        app = objects.registry.Application()
        assert app
        assert app.id is None

    def test_object_persist_and_retrieve(self):
        app = objects.registry.Application()
        assert app
        app.create(self.ctx)
        assert app.id is not None

        app2 = objects.registry.Application.get_by_id(None, app.id)
        assert app2
        assert app.id == app2.id

        query = utils.get_dummy_session().query(app.__class__)\
            .filter_by(id=app.id)
        app3 = query.first()
        assert app3
        assert app3.id == app.id
