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

import sqlalchemy

from solum.openstack.common import context
from solum.openstack.common.db.sqlalchemy.session import get_engine
from solum.openstack.common.db.sqlalchemy.session import get_session


def dummy_context(user='test_username', tenant_id='test_tenant_id'):
    return context.RequestContext(
        tenant=tenant_id,
        user=user,
        auth_token='abcd1234',
        is_admin=False,
        read_only=False,
        )


def setup_dummy_db():
    engine = get_engine()
    engine.connect()


def get_dummy_session():
    return get_session()


def reset_dummy_db():
    engine = get_engine()
    meta = sqlalchemy.MetaData()
    meta.reflect(bind=engine)

    for table in reversed(meta.sorted_tables):
        if table.name == 'migrate_version':
            continue
        engine.execute(table.delete())
