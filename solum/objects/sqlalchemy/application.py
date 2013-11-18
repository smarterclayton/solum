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

from sqlalchemy import Column, Integer

from solum.common import exception
from solum.objects import application as abstract
from solum.objects.sqlalchemy import models as sql
from solum.openstack.common import log as logging


LOG = logging.getLogger(__name__)


class Application(sql.Base, abstract.Application):
    """Represent an application in sqlalchemy."""

    __tablename__ = 'application'

    id = Column(Integer, primary_key=True)

    @classmethod
    def _duplicate_object(cls, e, self):
        raise exception.ApplicationExists(application_id=self.id)


class ApplicationList(abstract.ApplicationList):
    """Represent a list of applications in sqlalchemy."""

    @classmethod
    def get_all(cls, context):
        list_obj = ApplicationList()
        list_obj.objects = list(sql.model_query(context, Application))
        return list_obj
