# -*- coding: utf-8 -*-
#
# Copyright (C) 2005, TUBITAK/UEKAE
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# Please read the COPYING file.
#

# Package install operation

# Author:  Eray Ozkural <eray@uludag.org.tr>

import os

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

import pisi

import pisi.context as ctx
import pisi.packagedb as packagedb
import pisi.dependency as dependency
import pisi.operations as operations
from pisi.specfile import *
from pisi.package import Package
from pisi.metadata import MetaData
#import conflicts

class InstallError(pisi.Error):
    pass

class Installer:
    "Installer class, provides install routines for pisi packages"

    def __init__(self, package_fname):
        "initialize from a file name"
        self.package = Package(package_fname)
        self.package.read()
        self.metadata = self.package.metadata
        self.files = self.package.files
        self.pkginfo = self.metadata.package

    def install(self, ask_reinstall = True):
        "entry point"
        ctx.ui.info('Installing %s, version %s, release %s, build %s' %
                (self.pkginfo.name, self.pkginfo.version,
                 self.pkginfo.release, self.pkginfo.build))
        self.ask_reinstall = ask_reinstall
        self.check_requirements()
        self.check_relations()
        self.check_reinstall()
        self.extract_install()
        self.store_pisi_files()
        if ctx.comard:
            self.register_comar_scripts()
            self.comar_run_postinstall()
        self.update_databases()

    def check_requirements(self):
        """check system requirements"""
        #TODO: IS THERE ENOUGH SPACE?
        # what to do if / is split into /usr, /var, etc.
        pass

    def check_relations(self):
        # check if package is in database
        # If it is not, put it into 3rd party packagedb
        if not packagedb.has_package(self.pkginfo.name):
            db = packagedb.thirdparty_packagedb
            db.add_package(self.pkginfo)

        # check conflicts
        for pkg in self.metadata.package.conflicts:
            if ctx.installdb.is_installed(self.pkginfo):
                raise InstallError("Package conflicts " + pkg)

        # check dependencies
        if not ctx.config.get_option('ignore_dependency'):
            if not dependency.installable(self.pkginfo.name):
                ctx.ui.error(_('Dependencies for %s not satisfied') %
                             self.pkginfo.name)
                raise InstallError(_("Package not installable"))

    def check_reinstall(self):
        "check reinstall, confirm action, and schedule reinstall"

        pkg = self.pkginfo

        self.reinstall = False
        if ctx.installdb.is_installed(pkg.name): # is this a reinstallation?
            (iversion, irelease, ibuild) = ctx.installdb.get_version(pkg.name)

            # determine if same version
            same_ver = False
            ignore_build = ctx.config.options and ctx.config.options.ignore_build_no
            if (not ibuild) or (not pkg.build) or ignore_build:
                # we don't look at builds to compare two package versions
                if pkg.version == iversion and pkg.release == irelease:
                    same_ver = True
            else:
                if pkg.build == ibuild:
                    same_ver = True

            if same_ver:
                if self.ask_reinstall:
                    if not ctx.ui.confirm(_('Re-install same version package?')):
                        raise InstallError(_('Package re-install declined'))
            else:
                upgrade = False
                # is this an upgrade?
                # determine and report the kind of upgrade: version, release, build
                if pkg.version > iversion:
                    ctx.ui.info(_('Upgrading to new upstream version'))
                    upgrade = True
                elif pkg.release > irelease:
                    ctx.ui.info(_('Upgrading to new distribution release'))
                    upgrade = True
                elif ((not ignore_build) and ibuild and pkg.build
                       and pkg.build > ibuild):
                    ctx.ui.info(_('Upgrading to new distribution build'))
                    upgrade = True

                # is this a downgrade? confirm this action.
                if self.ask_reinstall and (not upgrade):
                    if pkg.version < iversion:
                        x = _('Downgrade to old upstream version?')
                    elif pkg.release < irelease:
                        x = _('Downgrade to old distribution release?')
                    else:
                        x = _('Downgrade to old distribution build?')
                    if not ctx.ui.confirm(x):
                        raise InstallError(_('Package downgrade declined'))

            # schedule for reinstall
            self.old_files = ctx.installdb.files(pkg.name)
            self.reinstall = True
            operations.run_preremove(pkg.name)

    def extract_install(self):
        "unzip package in place"

        ctx.ui.info(_('Extracting files'))
        self.package.extract_dir_flat('install', ctx.config.destdir)

        if self.reinstall:
            # remove left over files
            new = set(map(lambda x: str(x.path), self.files.list))
            old = set(map(lambda x: str(x.path), self.old_files.list))
            leftover = old - new
            old_fileinfo = {}
            for fileinfo in self.old_files.list:
                old_fileinfo[str(fileinfo.path)] = fileinfo
            for path in leftover:
                operations.remove_file( old_fileinfo[path] )

    def store_pisi_files(self):
        """put files.xml, metadata.xml, actions.py and COMAR scripts
        somewhere in the file system. We'll need these in future..."""

        ctx.ui.info(_('Storing %s, ') % ctx.const.files_xml)
        self.package.extract_file(ctx.const.files_xml, self.package.pkg_dir())

        ctx.ui.info(_('%s.') % ctx.const.metadata_xml)
        self.package.extract_file(ctx.const.metadata_xml, self.package.pkg_dir())

        for pcomar in self.metadata.package.providesComar:
            fpath = os.path.join(ctx.const.comar_dir, pcomar.script)
            # comar prefix is added to the pkg_dir while extracting comar
            # script file. so we'll use pkg_dir as destination.
            ctx.ui.info(_('Storing %s') % fpath)
            self.package.extract_file(fpath, self.package.pkg_dir())

    def register_comar_scripts(self):
        "register COMAR scripts"

        com = ctx.comard

        for pcomar in self.metadata.package.providesComar:
            scriptPath = os.path.join(self.package.comar_dir(),pcomar.script)
            ctx.ui.info(_("Registering COMAR script %s") % pcomar.script)

            com.register(pcomar.om,
                         self.metadata.package.name,
                         scriptPath)
            while 1:
                reply = com.read_cmd()
                if reply[0] == com.RESULT:
                    break
                else:
                    raise InstallError, _("COMAR.register ERROR!")


    def comar_run_postinstall(self):
        "run postinstall scripts trough COMAR"

        com = ctx.comard
        ctx.ui.info(_("Running postinstall script for %s") % self.metadata.package.name)
        com.call_package("System.Package.postInstall", self.metadata.package.name)
        while 1:
            reply = com.read_cmd()
            if reply[0] == com.RESULT:
                break
            elif reply[0] == com.NONE: # package has no postInstall script
                break
            elif reply[0] == com.FAIL:
                e = _("COMAR.call_package(System.Pakcage.postInstall, %s) failed!: %s") % (
                    self.metadata.package.name, reply[2])
                raise InstallError, e
            else:
                raise InstallError, _("COMAR.call_package ERROR: %d") % reply[0]


    def update_databases(self):
        "update databases"

        if self.reinstall:
            operations.remove_db(self.metadata.package.name)

        # installdb
        ctx.installdb.install(self.metadata.package.name,
                          self.metadata.package.version,
                          self.metadata.package.release,
                          self.metadata.package.build,
                          self.metadata.package.distribution)

        # installed packages
        packagedb.inst_packagedb.add_package(self.pkginfo)
