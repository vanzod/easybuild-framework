##
# Copyright 2015-2015 Ghent University
# Copyright 2015 S3IT, University of Zurich
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
Interface for submitting jobs via GC3Pie.

@author: Riccardo Murri (University of Zurich)
"""


import os
import time

try:
    import gc3libs
    from gc3libs import Application, Run, create_engine
    from gc3libs.core import Engine
    from gc3libs.quantity import hours as hr
    from gc3libs.workflow import DependentTaskCollection
    HAVE_GC3PIE = True
except ImportError:
    HAVE_GC3PIE = False

from easybuild.tools.build_log import print_msg
from easybuild.tools.config import build_option
from easybuild.tools.job.backend import JobBackend

from vsc.utils import fancylogger

if HAVE_GC3PIE:
    # inject EasyBuild logger into GC3Pie
    gc3libs.log = fancylogger.getLogger('gc3pie', fname=False)
    # make handling of log.error compatible with stdlib logging
    gc3libs.log.raiseError = False


# eb --job --job-backend=GC3Pie
class GC3Pie(JobBackend):
    """
    Use the GC3Pie__ framework to submit and monitor compilation jobs.

    In contrast with accessing an external service, GC3Pie implements
    its own workflow manager, which means ``eb --job
    --job-backend=GC3Pie`` will keep running until all jobs have
    terminated.

    .. __: http://gc3pie.googlecode.com/
    """

    USABLE = HAVE_GC3PIE

    # After polling for job status, sleep for this time duration
    # before polling again. Duration is expressed in seconds.
    POLL_INTERVAL = 30

    def init(self):
        """
        Initialise the job backend.

        Start a new list of submitted jobs.
        """
        self._jobs = DependentTaskCollection(
            output_dir=os.path.join(os.getcwd(), 'easybuild-jobs'))

    def make_job(self, script, name, env_vars=None, hours=None, cores=None):
        """
        Create and return a job object with the given parameters.

        First argument `server` is an instance of the corresponding
        `JobBackend` class, i.e., a `GC3Pie`:class: instance in this case.

        Second argument `script` is the content of the job script
        itself, i.e., the sequence of shell commands that will be
        executed.

        Third argument `name` sets the job human-readable name.

        Fourth (optional) argument `env_vars` is a dictionary with
        key-value pairs of environment variables that should be passed
        on to the job.

        Fifth and sixth (optional) arguments `hours` and `cores` should be
        integer values:
        * hours must be in the range 1 .. MAX_WALLTIME;
        * cores depends on which cluster the job is being run.
        """
        extra_args = {
            'jobname': name, # job name in GC3Pie
            'name':    name, # same in EasyBuild
        }
        if env_vars:
            extra_args['environment'] = env_vars
        if hours:
            extra_args['requested_walltime'] = hours*hr
        if cores:
            extra_args['requested_cores'] = cores
        return Application(
            # arguments
            ['/bin/sh', '-c', script],
            # no need to stage files in or out
            inputs=[],
            outputs=[],
            # where should the output (STDOUT/STDERR) files be downloaded to?
            output_dir=os.path.join(self._jobs.output_dir, name),
            # capture STDOUT and STDERR
            stdout='stdout.log',
            join=True,
            **extra_args
            )

    def queue(self, job, dependencies=frozenset()):
        """
        Add a job to the queue, optionally specifying dependencies.

        @param dependencies: jobs on which this job depends.
        """
        self._jobs.add(job, dependencies)

    def complete(self):
        """
        Complete a bulk job submission.

        Create engine, and progress it until all jobs have terminated.
        """
        # Create an instance of `Engine` using the configuration file present
        # in your home directory.
        self._engine = create_engine()

        # Add your application to the engine. This will NOT submit
        # your application yet, but will make the engine *aware* of
        # the application.
        self._engine.add(self._jobs)

        # in case you want to select a specific resource, call
        # `Engine.select_resource(<resource_name>)`

        # Periodically check the status of your application.
        while self._jobs.execution.state != Run.State.TERMINATED:
            # `Engine.progress()` will do the GC3Pie magic:
            # submit new jobs, update status of submitted jobs, get
            # results of terminating jobs etc...
            self._engine.progress()

            # report progress
            self._print_status_report(['total', 'SUBMITTED', 'RUNNING', 'ok', 'failed'])

            # Wait a few seconds...
            time.sleep(self.POLL_INTERVAL)

        # final status report
        self._print_status_report(['total', 'ok', 'failed'])

    def _print_status_report(self, states=('total', 'ok', 'failed'), **override):
        """
        Print a job status report to STDOUT and the log file.

        The number of jobs in any of the given states is reported; the
        figures are extracted from the `stats()` method of the
        currently-running GC3Pie engine.  Additional keyword arguments
        can override specific stats; this is used, e.g., to correctly
        report the number of total jobs right from the start.
        """
        stats = self._engine.stats(only=Application)
        job_overview = ', '.join(["%d %s" % (override.get(s, stats[s]), s.lower()) for s in states if stats[s]])
        print_msg("build jobs: %s" % job_overview, log=override.get('log', gc3libs.log), silent=build_option('silent'))
