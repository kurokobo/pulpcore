#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright © 2010 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public License,
# version 2 (GPLv2). There is NO WARRANTY for this software, express or
# implied, including the implied warranties of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. You should have received a copy of GPLv2
# along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
#
# Red Hat trademarks are not licensed under GPLv2. No permission is
# granted to use or replicate Red Hat trademarks that are incorporated
# in this software or its documentation.

"""
[[wiki]]
title: Repositories RESTful Interface
description: RESTfule interface for the creation, querying, and management of
             repositories managed by Pulp. Repositories are represented as
             Repo objects. Some of the Repo object fields
Repo object fields:
 * id (str) - repository identifier
 * source (RepoSource object) - upstream content source
 * name (str) - human-friendly name
 * arch (str) - hardware architecture that repository is for
 * release (str) - release number
 * packages (list of str) - list of package ids in the repository [deferred field]
 * package_count (int) - number of packages in the repository
 * packagegroups (object) - map of package group names to list of package ids in the group [deferred field]
 * packagegroupcategories (object) - map of categories to lists of package group names [deferred field]
 * repomd_xml_path (str) - path to the repository's repomd xml file
 * group_xml_path (str) - path to the repository's group xml file
 * group_gz_xml_path (str) - path to the repository's compressed group xml file
 * sync_schedule (str) - crontab entry representing recurring sync schedule
 * last_sync (timestamp) - date and time of last successful sync
 * use_symlinks (bool) - whether or not the repository uses symlinks for its content
 * ca (str) - the repository's certificate authority
 * cert (str) - the repository's certificate
 * key (str) - the repository's private key
 * errata (object) - map of errata names to lists of package ids in each errata [deferred field]
 * groupid (list of str) - list of repository group ids this repository belongs to
 * relative_path (str) - repository's path relative to the configured root
 * files (list of str) - list of ids of the non-package files in the repository [deferred field]
 * publish (bool) - whether or not the repository is available
 * clone_ids (list of str) - list of repository ids that are clones of this repository
 * distributionid (list of str) - list of distribution ids this repository belongs to [deferred fields]
 * checksum_type (str) - name of the algorithm used for checksums of the repository's content
 * filters (list of str) - list of filter ids associated with the repository
RepoSource object fields:
 * supported_types (list of str) - list of supported types of repositories
 * type (str) - repository source type
 * url (str) - repository source url
"""

import itertools
import logging

import web

from pulp.server.api.package import PackageApi
from pulp.server.api.repo import RepoApi
from pulp.server.async import find_async
from pulp.server.auth.authorization import grant_automatic_permissions_for_created_resource
from pulp.server.auth.authorization import CREATE, READ, UPDATE, DELETE, EXECUTE
from pulp.server.pexceptions import PulpException
from pulp.server.webservices import http
from pulp.server.webservices import mongo
from pulp.server.webservices.controllers.base import JSONController, AsyncController

# globals ---------------------------------------------------------------------

api = RepoApi()
pkg_api = PackageApi()
_log = logging.getLogger('pulp')

# default fields for repositories being sent to the client
default_fields = [
    'id',
    'source',
    'name',
    'arch',
    'sync_schedule',
    'last_sync',
    'use_symlinks',
    'groupid',
    'relative_path',
    'files',
    'publish',
    'clone_ids',
    'distributionid',
    'checksum_type',
    'filters'
]

# restful controllers ---------------------------------------------------------

class Repositories(JSONController):

    @JSONController.error_handler
    @JSONController.auth_required(READ)
    def GET(self):
        """
        [[wiki]]
        title: List Available Repositories
        description: Get a list of all repositories managed by Pulp.
        method: GET
        path: /repositories/
        permission: READ
        success response: 200 OK
        failure response: None
        return: list of Repo objects
        filters:
         * id (str) - repository id
         * name (str) - repository name
         * arch (str) repository contect architecture
         * groupid (str) - repository group id
         * relative_path (str) repository's on disk path
        """
        valid_filters = ['id', 'name', 'arch', 'groupid', 'relative_path']

        filters = self.filters(valid_filters)
        spec = mongo.filters_to_re_spec(filters)

        repositories = api.repositories(spec, default_fields)

        for repo in repositories:
            repo['uri_ref'] = http.extend_uri_path(repo['id'])
            repo['package_count'] = api.package_count(repo['id'])
            repo['files_count'] = len(repo['files'])
            for field in RepositoryDeferredFields.exposed_fields:
                repo[field] = http.extend_uri_path('/'.join((repo['id'], field)))

        return self.ok(repositories)

    @JSONController.error_handler
    @JSONController.auth_required(CREATE)
    def POST(self):
        """
        [[wiki]]
        title: Create a Repository
        description: Create a new repository based on the passed information
        method: POST
        path: /repositories/
        permission: CREATE
        success response: 201 Created
        failure response: 409 Conflict if the parameters matches an existing repository
        return: new Repo object
        parameters:
         * id (str)
         * name (str)
         * arch (str)
         * feed (str) - repository feed in the form of <type>:<url>
         * use_symlinks (bool) - optional, defaults to false
         * sync_schedule (str) - crontab entry format; optional
         * cert_data (str) - repository certificate information; optional
         * relative_path (str) - repository on disk path; optional
         * groupid (list of str) - list of repository group ids this repository belongs to; optional
         * gpgkeys (list of str) - list of gpg keys used for signing content; optional
         * checksum_type (str) - name of the algorithm to use for content checksums; optional, defaults to sha256
        """
        repo_data = self.params()

        id = repo_data['id']
        if api.repository(id, default_fields) is not None:
            return self.conflict('A repository with the id, %s, already exists' % id)

        repo = api.create(id,
                          repo_data['name'],
                          repo_data['arch'],
                          feed=repo_data.get('feed', None),
                          symlinks=repo_data.get('use_symlinks', False),
                          sync_schedule=repo_data.get('sync_schedule', None),
                          cert_data=repo_data.get('cert_data', None),
                          relative_path=repo_data.get('relative_path', None),
                          groupid=repo_data.get('groupid', None),
                          gpgkeys=repo_data.get('gpgkeys', None),
                          checksum_type=repo_data.get('checksum_type', 'sha256'))

        path = http.extend_uri_path(repo["id"])
        repo['uri_ref'] = path
        grant_automatic_permissions_for_created_resource(http.resource_path(path))
        return self.created(path, repo)

    def PUT(self):
        _log.debug('deprecated Repositories.PUT method called')
        return self.POST()

    @JSONController.error_handler
    @JSONController.auth_required(DELETE)
    def DELETE(self):
        """
        [[wiki]]
        title: Delete All Repositories
        description: Delete all repositories managed by Pulp.
        method: DELETE
        path: /repositories/
        permission: DELETE
        success response: 200 OK
        failure response: None
        return: True
        """
        api.clean()
        return self.ok(True)


class Repository(JSONController):

    @JSONController.error_handler
    @JSONController.auth_required(READ)
    def GET(self, id):
        """
        [[wiki]]
        title: Get A Repository
        description: Get a Repo object for a specific repository
        method: GET
        path: /repositories/<id>/
        permission: READ
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return: a Repo object
        """
        repo = api.repository(id, default_fields)
        if repo is None:
            return self.not_found('No repository %s' % id)
        for field in RepositoryDeferredFields.exposed_fields:
            repo[field] = http.extend_uri_path(field)
        repo['uri_ref'] = http.uri_path()
        #repo['package_count'] = api.package_count(id)
        # XXX this was a sersious problem with packages
        # why would packages be any different
        repo['files_count'] = len(repo['files'])
        return self.ok(repo)

    @JSONController.error_handler
    @JSONController.auth_required(UPDATE)
    def PUT(self, id):
        """
        [[wiki]]
        title: Update A Repository
        description: Change an exisiting repository.
        method: PUT
        path: /repositories/<id>/
        permission: UPDATE
        success response: 200 OK
        failure response: 400 Bad Request when trying to change the id
        return: true
        parameters: any field of a Repo object except id
        """
        delta = self.params()
        if delta.pop('id', id) != id:
            return self.bad_request('You cannot change a repository id')
        # we need to remove the substituted uri references
        # XXX we probably need to add the original data back as well
        for field in itertools.chain(['uri_ref'], # web services only field
                                     RepositoryDeferredFields.exposed_fields):
            if field in delta and isinstance(delta[field], basestring):
                delta.pop(field, None)
        api.update(id, delta)
        return self.ok(True)

    @JSONController.error_handler
    @JSONController.auth_required(DELETE)
    def DELETE(self, id):
        """
        [[wiki]]
        title: Delete A Repository
        description: Delete a single repository
        method: DELETE
        path: /repositories/<id>/
        permission: DELETE
        success response: 200 OK
        failure response: None
        return: true
        """
        api.delete(id=id)
        return self.ok(True)


class RepositoryDeferredFields(JSONController):

    # NOTE the intersection of exposed_fields and exposed_actions must be empty
    exposed_fields = (
        'packages',
        'packagegroups',
        'packagegroupcategories',
        'errata',
        'distribution',
        'files',
        'keys',
        'comps',
    )

    def packages(self, id):
        """
        [[wiki]]
        title: Repository Packages
        description: Get the packages in a repository
        method: GET
        path: /repositories/<id>/packages/
        permission: READ
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return: list of Package objects
        filters:
         * name (str) - package name
         * version (str) - package version
         * release (str) - package release
         * epoch (int) - package epoch
         * arach (str) - package architecture 
         * filename (str) - name of package file
         * field (str) - field to include in Package objects
        """
        valid_filters = ('name', 'version', 'release', 'epoch', 'arch',
                        'filename', 'field')
        filters = self.filters(valid_filters)
        fields = filters.pop('filed', None)
        spec = mongo.filters_to_re_spec(filters) or {}
        try:
            packages = api.get_packages(id, spec, fields)
        except PulpException: # XXX this isn't specific enough!
            return self.not_found('No repository %s' % id)
        else:
            return self.ok(packages)

    def packagegroups(self, id):
        """
        [[wiki]]
        title: Repository Package Groups
        description: Get the package groups in the repositories.
        method: GET
        path: /repositories/<id>/packagegroups/
        permission: READ
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return: list of package group names
        filters:
         * id (str) - package groupd id
         * packagegroups (str) - package group name
        """
        repo = api.repository(id, ['id', 'packagegroups'])
        if repo is None:
            return self.not_found('No repository %s' % id)
        return self.ok(repo.get('packagegroups'))

    def packagegroupcategories(self, id):
        """
        [[wiki]]
        title: Repository Package Group Categories
        description: Get the package group categories in the repository.
        method: GET
        path: /repositories/<id>/packagegroupcategories/
        permission: READ
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return: list of package group catagory names
        filters:
         * id (str) - package group category id
         * packagegroupcategories (str) - package group category name
        """
        repo = api.repository(id, ['id', 'packagegroupcategories'])
        if repo is None:
            return self.not_found('No repository %s' % id)
        return self.ok(repo.get('packagegroupcategories', []))

    def errata(self, id):
        """
        [[wiki]]
        title: Repository Errata
        description: List the applicable errata for the repository.
        method: GET
        path: /repositories/<id>/errata/
        permission: READ
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return: list of Errata objects
        filters:
         * type (str) - type of errata
        """
        valid_filters = ('type')
        types = self.filters(valid_filters).get('type', [])
        return self.ok(api.errata(id, types))

    def distribution(self, id):
        """
        [[wiki]]
        title: Repository Distribution
        description: List the distributions the repository is part of.
        method: GET
        path: /repositories/<id>/distribution/
        permission: READ
        success response: 200 OK
        failure response: None
        return: list of Distribution objects
        """
        return self.ok(api.list_distributions(id))

    def files(self, id):
        """
        [[wiki]]
        title: Repository Files
        description: List the non-package files in the repository.
        method: GET
        path: /repositories/<id>/files/
        permission: READ
        success response: 200 OK
        failure response: None
        return: list of File objects
        """
        return self.ok(api.list_files(id))

    def keys(self, id):
        """
        [[wiki]]
        title: Repository GPG Keys
        description: List the gpg keys used by the repository.
        method: GET
        path: /repositories/<id>/keys/
        permission: READ
        success response: 200 OK
        failure response: None
        return: list of gpg keys
        """
        keylist = api.listkeys(id)
        return self.ok(keylist)

    def comps(self, id):
        """
        [[wiki]]
        title: Repository Comps XML
        description: Get the xml content of the repository comps file
        method: GET
        path: /repositories/<id>/comps/
        permission: READ
        success response: 200 OK
        failure response: None
        return: xml comps file
        """
        return self.ok(api.export_comps(id))

    @JSONController.error_handler
    @JSONController.auth_required(READ)
    def GET(self, id, field_name):
        field = getattr(self, field_name, None)
        if field is None:
            return self.internal_server_error('No implementation for %s found' % field_name)
        return field(id)


class RepositoryActions(AsyncController):

    # All actions have been gathered here into one controller class for both
    # convenience and automatically generate the regular expression that will
    # map valid actions to this class. This also provides a single point for
    # querying existing tasks.
    #
    # There are two steps to implementing a new action:
    # 1. The action name must be added to the tuple of exposed_actions
    # 2. You must add a method to this class with the same name as the action
    #    that takes two positional arguments: 'self' and 'id' where id is the
    #    the repository id. Additional parameters from the body can be
    #    fetched and de-serialized via the self.params() call.

    # NOTE the intersection of exposed_actions and exposed_fields must be empty
    exposed_actions = (
        'sync',
        '_sync',
        'clone',
        'upload',
        'add_package',
        'delete_package',
        'get_package',
        'add_file',
        'remove_file',
        'add_packages_to_group',
        'delete_package_from_group',
        'delete_packagegroup',
        'create_packagegroup',
        'create_packagegroupcategory',
        'delete_packagegroupcategory',
        'add_packagegroup_to_category',
        'delete_packagegroup_from_category',
        'add_errata',
        'delete_errata',
        'get_package_by_nvrea',
        'get_package_by_filename',
        'addkeys',
        'rmkeys',
        'update_publish',
        'import_comps',
        'add_filters',
        'remove_filters',
        'add_group',
        'remove_group'
    )

    def sync(self, id):
        """
        [[wiki]]
        title: Repository Sychronization
        description: Synchronize the repository's content from its source.
        method: POST
        path: /repositories/<id>/sync/
        permission: EXECUTE
        success response: 202 Accepted 
        failure response: 406 Not Acceptable if the repository does not have a source;
                          409 Conflict if a sync is already in progress for the repository
        return: a Task object
        parameters:
         * timeout (str) - timeout in <value>:<units> format (e.g. 2:hours)
         * skip (object) - yum skip dict
        """
        repo = api.repository(id, fields=['source'])
        if repo['source'] is None:
            return self.not_acceptable('Repo [%s] is not setup for sync. Please add packages using upload.' % id)
        repo_params = self.params()
        timeout = self.timeout(repo_params)
        skip = repo_params.get('skip', {})
        task = api.sync(id, timeout, skip)
        if not task:
            return self.conflict('Sync already in process for repo [%s]' % id)
        task_info = self._task_to_dict(task)
        task_info['status_path'] = self._status_path(task.id)
        return self.accepted(task_info)

    # XXX hack to make the web services unit tests work
    _sync = sync

    def clone(self, id):
        """
        [[wiki]]
        title: Repository Clone
        description: Create a new repository by cloning an existing one.
        method: POST
        path: /repositories/<id>/clone/
        permission: EXECUTE
        success response: 202 Accepted
        failure response: 404 Not Found if the id does not match a repository;
                          409 Conflict if the parameters match an existing repository;
        return: a Task object
        parameters:
         * clone_id (str) - the id of the clone repository
         * clone_name (str) - the namd of clone repository
         * feed (str) - feed of the clone repository in <type>:<url> format
         * relative_path (str) - clone repository on disk path; optional
         * groupid (str) - repository groups that clone belongs to
         * filters (list of objects) - synchronization filters to apply to the clone
        """
        repo_data = self.params()
        if api.repository(id, default_fields) is None:
            return self.not_found('A repository with the id, %s, does not exist' % id)
        if api.repository(repo_data['clone_id'], default_fields) is not None:
            return self.conflict('A repository with the id, %s, already exists' % repo_data['clone_id'])

        task = api.clone(id,
                         repo_data['clone_id'],
                         repo_data['clone_name'],
                         repo_data['feed'],
                         relative_path=repo_data.get('relative_path', None),
                         groupid=repo_data.get('groupid', None),
                         filters=repo_data.get('filters', []))
        if not task:
            return self.conflict('Error in cloning repo [%s]' % id)
        task_info = self._task_to_dict(task)
        task_info['status_path'] = self._status_path(task.id)
        return self.accepted(task_info)

    # TODO I'm right here

    def upload(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        api.upload(id,
                   data['pkginfo'],
                   data['pkgstream'])
        return self.ok(True)

    def add_package(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        errors = api.add_package(id, data['packageid'])
        return self.ok(errors)

    def delete_package(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        api.remove_packages(id, data['package'])
        return self.ok(True)

    def get_package(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        """
        @deprecated: use deferred fields: packages with filters instead
        """
        name = self.params()
        return self.ok(api.get_package(id, name))

    def add_packages_to_group(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        p = self.params()
        if "groupid" not in p:
            return self.not_found('No groupid specified')
        if "packagenames" not in p:
            return self.not_found('No package name specified')
        groupid = p["groupid"]
        pkg_names = p.get('packagenames', [])
        gtype = "default"
        requires = None
        if p.has_key("type"):
            gtype = p["type"]
        if p.has_key("requires"):
            requires = p["requires"]
        return self.ok(api.add_packages_to_group(id, groupid, pkg_names, gtype, requires))

    def delete_package_from_group(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        p = self.params()
        if "groupid" not in p:
            return self.not_found('No groupid specified')
        if "name" not in p:
            return self.not_found('No package name specified')
        groupid = p["groupid"]
        pkg_name = p["name"]
        gtype = "default"
        if p.has_key("type"):
            gtype = p["type"]
        requires = None
        return self.ok(api.delete_package_from_group(id, groupid, pkg_name, gtype))

    def create_packagegroup(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        p = self.params()
        if "groupid" not in p:
            return self.not_found('No groupid specified')
        groupid = p["groupid"]
        if "groupname" not in p:
            return self.not_found('No groupname specified')
        groupname = p["groupname"]
        if "description" not in p:
            return self.not_found('No description specified')
        descrp = p["description"]
        return self.ok(api.create_packagegroup(id, groupid, groupname,
                                               descrp))

    def import_comps(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        comps_data = self.params()
        return self.ok(api.import_comps(id, comps_data))

    def delete_packagegroup(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        p = self.params()
        if "groupid" not in p:
            return self.not_found('No groupid specified')
        groupid = p["groupid"]
        return self.ok(api.delete_packagegroup(id, groupid))

    def create_packagegroupcategory(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        _log.info("create_packagegroupcategory invoked")
        p = self.params()
        if "categoryid" not in p:
            return self.not_found('No categoryid specified')
        categoryid = p["categoryid"]
        if "categoryname" not in p:
            return self.not_found('No categoryname specified')
        categoryname = p["categoryname"]
        if "description" not in p:
            return self.not_found('No description specified')
        descrp = p["description"]
        return self.ok(api.create_packagegroupcategory(id, categoryid, categoryname,
                                               descrp))

    def delete_packagegroupcategory(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        _log.info("delete_packagegroupcategory invoked")
        p = self.params()
        if "categoryid" not in p:
            return self.not_found('No categoryid specified')
        categoryid = p["categoryid"]
        return self.ok(api.delete_packagegroupcategory(id, categoryid))

    def add_packagegroup_to_category(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        _log.info("add_packagegroup_to_category invoked")
        p = self.params()
        if "categoryid" not in p:
            return self.not_found("No categoryid specified")
        if "groupid" not in p:
            return self.not_found('No groupid specified')
        groupid = p["groupid"]
        categoryid = p["categoryid"]
        return self.ok(api.add_packagegroup_to_category(id, categoryid, groupid))

    def delete_packagegroup_from_category(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        _log.info("delete_packagegroup_from_category")
        p = self.params()
        if "categoryid" not in p:
            return self.not_found("No categoryid specified")
        if "groupid" not in p:
            return self.not_found('No groupid specified')
        groupid = p["groupid"]
        categoryid = p["categoryid"]
        return self.ok(api.delete_packagegroup_from_category(id, categoryid, groupid))

    def add_errata(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        api.add_errata(id, data['errataid'])
        return self.ok(True)

    def delete_errata(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        api.delete_errata(id, data['errataid'])
        return self.ok(True)

    def add_file(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        api.add_file(id, data['fileids'])
        return self.ok(True)

    def remove_file(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        api.remove_file(id, data['fileids'])
        return self.ok(True)

    def addkeys(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        api.addkeys(id, data['keylist'])
        return self.ok(True)

    def get_package_by_nvrea(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        return self.ok(api.get_packages_by_nvrea(id, data['nvrea']))

    def get_package_by_filename(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        return self.ok(api.get_packages_by_filename(id, data['filename']))

    def rmkeys(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        api.rmkeys(id, data['keylist'])
        return self.ok(True)

    def add_filters(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        api.add_filters(id=id, filter_ids=data['filters'])
        return self.ok(True)

    def remove_filters(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        api.remove_filters(id=id, filter_ids=data['filters'])
        return self.ok(True)
    
    def add_group(self, id):
        """
        @param id: repository id
        @return: True on successful addition of group to repository
        """
        data = self.params()
        api.add_group(id=id, addgrp=data['addgrp'])
        return self.ok(True)

    def remove_group(self, id):
        """
        @param id: repository id
        @return: True on successful removal of group from repository
        """
        data = self.params()
        api.remove_group(id=id, rmgrp=data['rmgrp'])
        return self.ok(True)

    def update_publish(self, id):
        """
        [[wiki]]
        title:
        description:
        method: POST
        path: /repositories/<id>/
        permission: EXECUTE
        success response: 200 OK
        failure response: 404 Not Found if the id does not match a repository
        return:
        parameters:
        """
        data = self.params()
        return self.ok(api.publish(id, bool(data['state'])))

    @JSONController.error_handler
    @JSONController.auth_required(EXECUTE)
    def POST(self, id, action_name):
        """
        Action dispatcher. This method checks to see if the action is exposed,
        and if so, implemented. It then calls the corresponding method (named
        the same as the action) to handle the request.
        @type id: str
        @param id: repository id
        @type action_name: str
        @param action_name: name of the action
        @return: http response
        """
        repo = api.repository(id, fields=['id'])
        if not repo:
            return self.not_found('No repository with id %s found' % id)
        action = getattr(self, action_name, None)
        if action is None:
            return self.internal_server_error('No implementation for %s found' % action_name)
        return action(id)

    @JSONController.error_handler
    @JSONController.auth_required(READ)
    def GET(self, id, action_name):
        """
        Get information on a given action and repository.
        """
        action_methods = {
            'sync': '_sync',
            '_sync': '_sync',
        }
        if action_name not in action_methods:
            return self.not_found('No information for %s on repository %s' %
                                 (action_name, id))
        tasks = [t for t in find_async(method_name=action_methods[action_name])
                 if (t.args and id in t.args) or
                 (t.kwargs and id in t.kwargs.values())]
        if not tasks:
            return self.not_found('No recent %s on repository %s found' %
                                 (action_name, id))
        task_infos = []
        for task in tasks:
            info = self._task_to_dict(task)
            info['status_path'] = self._status_path(task.id)
            task_infos.append(info)
        return self.ok(task_infos)


class RepositoryActionStatus(AsyncController):

    @JSONController.error_handler
    @JSONController.auth_required(EXECUTE) # this is checking an execute, not reading a resource
    def GET(self, id, action_name, action_id):
        """
        Check the status of a sync operation.
        @param id: repository id
        @param action_name: name of the action
        @param action_id: action id
        @return: action status information
        """
        task_info = self.task_status(action_id)
        if task_info is None:
            return self.not_found('No %s with id %s found' % (action_name, action_id))
        return self.ok(task_info)

    @JSONController.error_handler
    @JSONController.auth_required(EXECUTE) # this is stopping an execute, not deleting a resource
    def DELETE(self, id, action_name, action_id):
        """
        Cancel an action
        """
        task = self.find_task(action_id)
        if task is None:
            return self.not_found('No %s with id %s found' % (action_name, action_id))
        if self.cancel_task(task):
            return self.accepted(self._task_to_dict(task))
        # action is complete and, therefore, not canceled
        # a no-content return means the client should *not* adjust its view of
        # the resource
        return self.no_content()


class Schedules(JSONController):

    @JSONController.error_handler
    @JSONController.auth_required(READ)
    def GET(self):
        '''
        Retrieve a map of all repository IDs to their associated synchronization
        schedules.

        @return: key - repository ID, value - synchronization schedule
        '''
        # XXX this returns all scheduled tasks, it should only return those
        # tasks that are specified by the action_name
        schedules = api.all_schedules()
        return self.ok(schedules)

# web.py application ----------------------------------------------------------

urls = (
    '/$', 'Repositories',
    '/schedules/', 'Schedules',
    '/([^/]+)/$', 'Repository',

    '/([^/]+)/(%s)/$' % '|'.join(RepositoryDeferredFields.exposed_fields),
    'RepositoryDeferredFields',

    '/([^/]+)/(%s)/$' % '|'.join(RepositoryActions.exposed_actions),
    'RepositoryActions',

    '/([^/]+)/(%s)/([^/]+)/$' % '|'.join(RepositoryActions.exposed_actions),
    'RepositoryActionStatus',
)

application = web.application(urls, globals())
