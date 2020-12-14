# vim: sw=4:ts=4:et

import datetime
import json
import locale
import logging
import logging.config
import os
import os.path
import pathlib
import shutil
import socket
import sys
import time
import traceback
import urllib

from getpass import getpass

from ace.configuration import load_configuration, import_encrypted_passwords
from ace.constants import *
#from ace.messaging import initialize_message_system
#from ace.network_semaphore import initialize_fallback_semaphores
#from ace.sla import SLA
#from ace.util import create_directory

import pytz
#import requests
import tzlocal

# this is set to True when unit testing, False otherwise
UNIT_TESTING = 'SAQ_UNIT_TESTING' in os.environ

# global user ID for the "automation" user
AUTOMATION_USER_ID = None # (initialized in ace.database.initialize_database())

# disable the verbose logging in the requests module
#logging.getLogger("requests").setLevel(logging.WARNING)

# local timezone
LOCAL_TIMEZONE = pytz.timezone(tzlocal.get_localzone().zone)

# the global sqlalchemy.orm.scoped_session object
# this object is used to get Session objects by ACE throughout the application
# except for the WSGI app which uses Flask
db = None # (see ace.database.initialize_database)

# the global message system, used to send external messages async
MESSAGE_SYSTEM = None

class CustomFileHandler(logging.StreamHandler):
    def __init__(self, log_dir=None, filename_format=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stream = None

        # the directory to store the log files in
        self.log_dir = log_dir
        if self.log_dir is None:
            self.log_dir = '.'

        # the format to use to generate the filename
        self.filename_format = filename_format
        if self.filename_format is None:
            self.filename_format = '%Y-%m-%d-%H.log'

        # the current file name we're using
        self.current_filename = None
        self._update_stream()

    def _update_stream(self):
        # what should the file name be right now?
        current_filename = datetime.datetime.now().strftime(self.filename_format)

        # did the name change?
        if self.current_filename != current_filename:
            # close the current stream
            if self.stream:
                try:
                    self.stream.close()
                except OSError as e:
                    logging.warning(f"Error closing stream: {e}")
            
            # and open a new one
            self.stream = open(os.path.join(self.log_dir, current_filename), 'a')
            self.current_filename = current_filename

    def emit(self, record):
        self.acquire()
        try:
            self._update_stream()
            super().emit(record)
        finally:
            self.release()

# base configuration for logging
LOGGING_BASE_CONFIG = {
    'version': 1,
    'formatters': {
        'base': {
            'format': 
                '[%(asctime)s] [%(pathname)s:%(funcName)s:%(lineno)d] [%(threadName)s] [%(process)d] [%(levelname)s] - %(message)s',
        },
    },
}

def initialize_logging(logging_config_path):
    try:
        logging.config.fileConfig(logging_config_path, disable_existing_loggers=False)
    except Exception as e:
        sys.stderr.write("unable to load logging configuration: {}".format(e))
        raise e

    # log all SQL commands if we are running in debug mode
    if CONFIG['global'].getboolean('log_sql'):
        logging.getLogger('sqlalchemy.engine').setLevel(logging.DEBUG)
        #logging.getLogger('sqlalchemy.dialects').setLevel(logging.DEBUG)
        #logging.getLogger('sqlalchemy.pool').setLevel(logging.DEBUG)
        #logging.getLogger('sqlalchemy.orm').setLevel(logging.DEBUG)

def set_node(name):
    """Sets the value for ace.SAQ_NODE. Typically this is auto-set using the local fqdn."""
    from ace.database import initialize_node
    global SAQ_NODE
    global SAQ_NODE_ID
    
    if name != SAQ_NODE:
        SAQ_NODE = name
        SAQ_NODE_ID = None
        initialize_node()

def initialize(
        ace_home=None,
        config_paths=[],
        logging_config_path=None,
        args=None,
        relative_dir=None):

    #from ace.database import initialize_database, initialize_node, initialize_automation_user

    global API_PREFIX
    global AUTOMATION_USER_ID
    global CA_CHAIN_PATH
    global CONFIG
    global CONFIG_PATHS
    global DAEMON_DIR
    global DAEMON_MODE
    global DATA_DIR
    global DEFAULT_ENCODING
    global DUMP_TRACEBACKS
    global ECS_SOCKET_PATH
    global ENCRYPTION_INITIALIZED
    global ENCRYPTION_PASSWORD
    global ENCRYPTION_PASSWORD_PLAINTEXT
    global EXCLUDED_SLA_ALERT_TYPES
    global EXECUTION_THREAD_LONG_TIMEOUT
    global FORCED_ALERTS
    global GLOBAL_SLA_SETTINGS
    global GUI_WHITELIST_EXCLUDED_OBSERVABLE_TYPES
    global INSTANCE_TYPE
    global LOCAL_DOMAINS
    global LOCK_TIMEOUT_SECONDS
    global LOG_DIRECTORY
    global LOG_LEVEL
    global MANAGED_NETWORKS
    global MODULE_STATS_DIR
    global OTHER_PROXIES 
    global OTHER_SLA_SETTINGS
    global SAQ_HOME
    global SAQ_NODE
    global SAQ_NODE_ID
    global SAQ_RELATIVE_DIR
    global SEMAPHORES_ENABLED
    global SERVICES_DIR
    global STATS_DIR
    global TEMP_DIR
    global TOR_PROXY

    SAQ_HOME = None
    SAQ_NODE = None
    SAQ_NODE_ID = None
    API_PREFIX = None
    SAQ_RELATIVE_DIR = None
    CONFIG = None
    CONFIG_PATHS = []
    DATA_DIR = None
    TEMP_DIR = None
    DEFAULT_ENCODING = None
    SEMAPHORES_ENABLED = False
    OTHER_PROXIES = {}
    TOR_PROXY = None
    # list of iptools.IpRange objects defined in [network_configuration]
    MANAGED_NETWORKS = None
    # set this to True to force all anlaysis to result in an alert being generated
    FORCED_ALERTS = False
    # the private key password for encrypting/decrypting archive files
    # NOTE this is the decrypted random string of bytes that is used to encrypt/decrypt using AES
    # NOTE both of these can stay None if encryption is not being used
    ENCRYPTION_PASSWORD = None
    # *this* is the password that is used to encrypt/decrypt the ENCRYPTION_PASSWORD at rest
    ENCRYPTION_PASSWORD_PLAINTEXT = None
    # set to True after we've initialized encryption
    ENCRYPTION_INITIALIZED = False

    # the global log level setting
    LOG_LEVEL = logging.INFO
    # global logging directory (relative to DATA_DIR)
    LOG_DIRECTORY = None

    # directory containing statistical runtime info
    STATS_DIR = None 
    MODULE_STATS_DIR = None

    # are we running as a daemon in the background?
    DAEMON_MODE = False

    # directory where pid files are stored for daemons
    DAEMON_DIR = None

    # directory where files are stored for running services
    SERVICES_DIR = None

    # path to the certifcate chain used by all SSL certs
    CA_CHAIN_PATH = None

    # what type of instance is this?
    INSTANCE_TYPE = None

    # SLA settings
    GLOBAL_SLA_SETTINGS = None
    OTHER_SLA_SETTINGS = []
    EXCLUDED_SLA_ALERT_TYPES = []

    # set to True to cause tracebacks to be dumped to standard output
    # useful when debugging or testing
    DUMP_TRACEBACKS = False

    # the amount of time (in seconds) that a lock in the locks table is valid
    LOCK_TIMEOUT_SECONDS = None

    # amount of time (in seconds) before a process blows up because a threaded module won't stop
    EXECUTION_THREAD_LONG_TIMEOUT = None

    # go ahead and try to figure out what text encoding we're using
    DEFAULT_ENCODING = locale.getpreferredencoding()

    # list of observable types we want to exclude from whitelisting (via the GUI)
    GUI_WHITELIST_EXCLUDED_OBSERVABLE_TYPES = []

    # do we want to force alerts?
    if args:
        FORCED_ALERTS = args.force_alerts

    # where is ACE?
    # this parent directory of this file is the default
    # this usually all you need
    SAQ_HOME = str(pathlib.Path(os.path.abspath(__file__)).parent.parent)

    # optional override from the environment
    if 'SAQ_HOME' in os.environ: 
        SAQ_HOME = os.environ['SAQ_HOME']

    # or you can specify directly
    if ace_home:
        SAQ_HOME = ace_home

    if not os.path.isdir(SAQ_HOME):
        sys.stderr.write(f"invalid root ACE directory {SAQ_HOME}\n")
        sys.exit(1) # TODO refactor to use exceptions for unit testing instead of sys.exit

    # path to the unix socket for the optional encryption cache service
    ECS_SOCKET_PATH = os.path.join(SAQ_HOME, '.ecs')

    # XXX not sure we need this SAQ_RELATIVE_DIR anymore -- check it out
    # this system was originally designed to run out of /opt/saq
    # later we modified to run out of anywhere for command line correlation
    # when running the GUI in apache you have no control over the current working directory
    # so we specify what directory we'd *want* to be running out of here (even if we're not actually)
    # this only matters when loading alerts
    # this defaults to the current working directory
    SAQ_RELATIVE_DIR = os.path.relpath(os.getcwd(), start=SAQ_HOME)
    if relative_dir:
        SAQ_RELATIVE_DIR = relative_dir

    # load configuration files
    # defaults to $SAQ_HOME/etc/saq.ini
    if config_paths is None:
        config_paths = []
    
    CONFIG_PATHS = []

    # add any config files specified in SAQ_CONFIG_PATHS env var (command separated)
    if 'SAQ_CONFIG_PATHS' in os.environ:
        for config_path in os.environ['SAQ_CONFIG_PATHS'].split(','):
            config_path = config_path.strip()
            if not os.path.isabs(config_path):
                config_path = os.path.join(SAQ_HOME, config_path)
            if not os.path.exists(config_path):
                sys.stderr.write(f"WARNING: config path {config_path} specified in SAQ_CONFIG_PATHS env var does not exist\n")
            else:
                if config_path not in CONFIG_PATHS:
                    CONFIG_PATHS.append(config_path)

    # and then add any specified on the command line
    for config_path in config_paths:
        if not os.path.isabs(config_path):
            config_path = os.path.join(SAQ_HOME, config_path)
            if not os.path.exists(config_path):
                sys.stderr.write(f"WARNING: config path {config_path} specified on the command line does not exist\n")
            else:
                if config_path not in CONFIG_PATHS:
                    CONFIG_PATHS.append(config_path)

    # XXX get rid of this logic
    if UNIT_TESTING:
        # unit testing loads different configurations
        CONFIG_PATHS.append(os.path.join(SAQ_HOME, 'etc', 'saq.unittest.default.ini'))
        CONFIG_PATHS.append(os.path.join(SAQ_HOME, 'etc', 'saq.unittest.ini'))
    else:
        CONFIG_PATHS.append(os.path.join(SAQ_HOME, 'etc', 'saq.ini'))

    try:
        CONFIG = load_configuration()
    except Exception as e:
        sys.stderr.write(f"ERROR: unable to load configuration: {e}")
        raise
        #sys.exit(1) # TODO replace with exception for unit testing

    DATA_DIR = os.path.join(SAQ_HOME, CONFIG['global']['data_dir'])
    TEMP_DIR = os.path.join(DATA_DIR, CONFIG['global']['tmp_dir'])
    DAEMON_DIR = os.path.join(DATA_DIR, 'var', 'daemon')
    SERVICES_DIR = os.path.join(DATA_DIR, 'var', 'services')
    LOCAL_DOMAINS = [_.strip() for _ in CONFIG['global']['local_domains'].split(',')]

    minutes, seconds = map(int, CONFIG['global']['lock_timeout'].split(':'))
    LOCK_TIMEOUT_SECONDS = (minutes * 60) + seconds
    EXECUTION_THREAD_LONG_TIMEOUT = CONFIG['global'].getint('execution_thread_long_timeout')

    # user specified log level
    LOG_LEVEL = logging.INFO
    if args:
        if args.log_level:
            LOG_LEVEL = args.log_level

    # make sure the logs directory exists
    LOG_DIRECTORY = os.path.join(DATA_DIR, 'logs')
    if not os.path.exists(LOG_DIRECTORY):
        try:
            os.mkdir(LOG_DIRECTORY)
        except Exception as e:
            sys.stderr.write("unable to mkdir {}: {}\n".format(LOG_DIRECTORY, e))
            sys.exit(1)

    # by default we log to the console
    if logging_config_path is None:
        logging_config_path = os.path.join(SAQ_HOME, 'etc', 'console_logging.ini')

    # we can override this on the command line
    # this is what we use for production engine settings
    if args:
        if args.logging_config_path:
            logging_config_path = args.logging_config_path
    
    # we can re-initialize later if we have to
    try:
        initialize_logging(logging_config_path) # this log file just gets some startup information
    except Exception as e:
        sys.exit(1)

    # has the encryption password been set yet?
    import ace.crypto
    from ace.crypto import get_aes_key, InvalidPasswordError

    # XXX get rid of these checks for UNIT_TESTING
    if not ace.UNIT_TESTING:
        try:
            # are we prompting for the decryption password?
            if args and args.set_decryption_password:
                ENCRYPTION_PASSWORD_PLAINTEXT = args.set_decryption_password
                ENCRYPTION_PASSWORD = get_aes_key(ENCRYPTION_PASSWORD_PLAINTEXT)
            elif args and args.provide_decryption_password:
                while True:
                    ENCRYPTION_PASSWORD_PLAINTEXT = getpass("Enter the decryption password:")
                    try:
                        ENCRYPTION_PASSWORD = get_aes_key(ENCRYPTION_PASSWORD_PLAINTEXT)
                    except InvalidPasswordError:
                        logging.error("invalid encryption password")
                        continue

                    break

            elif ace.crypto.encryption_key_set():
                # if we're not prompting for it then we can do one of two things
                # 1) pass it in via an environment variable SAQ_ENC
                # 2) run the encryption cache service 
                if 'SAQ_ENC' in os.environ:
                    logging.debug("reading encryption password from environment variable")
                    ENCRYPTION_PASSWORD_PLAINTEXT = os.environ['SAQ_ENC']
                    del os.environ['SAQ_ENC']
                else:
                    logging.debug("reading encryption password from ecs")
                    ENCRYPTION_PASSWORD_PLAINTEXT = ace.crypto.read_ecs()

                if ENCRYPTION_PASSWORD_PLAINTEXT is not None:
                    try:
                        ENCRYPTION_PASSWORD = get_aes_key(ENCRYPTION_PASSWORD_PLAINTEXT)
                    except InvalidPasswordError:
                        logging.error("read password from ecs but the password is wrong")
                        ENCRYPTION_PASSWORD_PLAINTEXT = None

        except Exception as e:
            logging.error(f"unable to get encryption key: {e}")

    ENCRYPTION_INITIALIZED = True

    GUI_WHITELIST_EXCLUDED_OBSERVABLE_TYPES = [_.strip() for _ in 
                                               CONFIG['gui']['whitelist_excluded_observable_types'].split(',')]

    #for o_type in GUI_WHITELIST_EXCLUDED_OBSERVABLE_TYPES:
        #if o_type not in VALID_OBSERVABLE_TYPES:
            #logging.error(f"invalid observable type {o_type} specified in [gui] whitelist_excluded_observable_types")

    # make this a faster lookup
    GUI_WHITELIST_EXCLUDED_OBSERVABLE_TYPES = set(GUI_WHITELIST_EXCLUDED_OBSERVABLE_TYPES)

    # load global SLA settings
    # XXX move to gui
    #GLOBAL_SLA_SETTINGS = SLA(None, 
                              #CONFIG['SLA'].getboolean('enabled'),
                              #CONFIG['SLA'].getint('time_to_dispo'),
                              #CONFIG['SLA'].getint('approaching_warn'),
                              #None, None)

    #EXCLUDED_SLA_ALERT_TYPES = [x.strip() for x in CONFIG['SLA']['excluded_alert_types'].split(',')]

    # load all the other SLA settings
    #for section in [s for s in CONFIG.keys() if s.startswith('SLA_')]:
        #logging.debug("loading {}".format(section))
        #OTHER_SLA_SETTINGS.append(SLA(section[len('SLA_'):],
                                      #CONFIG[section].getboolean('enabled'),
                                      #CONFIG[section].getint('time_to_dispo'),
                                      #CONFIG[section].getint('approaching_warn'),
                                      #CONFIG[section]['property'],
                                      #CONFIG[section]['value']))

    # what node is this?
    try:
        SAQ_NODE = CONFIG['global']['node']
        if SAQ_NODE == 'AUTO':
            SAQ_NODE = socket.getfqdn()
    except Exception as e:
        sys.stderr.write("unable to get hostname: {}\n".format(e))
        sys.exit(1)

    # what prefix do other systems use to communicate to the API server for this node?
    try:
        API_PREFIX = CONFIG['api']['prefix']
        if API_PREFIX == 'AUTO':
            API_PREFIX = socket.getfqdn()
        logging.debug("node {} has api prefix {}".format(SAQ_NODE, API_PREFIX))
    except Exception as e:
        sys.stderr.write("unable to get hostname: {}\n".format(e))
        sys.exit(1)

    # what type of instance is this?
    INSTANCE_TYPE = CONFIG['global']['instance_type']
    if INSTANCE_TYPE not in [ INSTANCE_TYPE_PRODUCTION, INSTANCE_TYPE_QA, INSTANCE_TYPE_DEV, INSTANCE_TYPE_UNITTEST ]:
        logging.fatal("invalid instance type {}".format(INSTANCE_TYPE))
        sys.exit(1)

    if FORCED_ALERTS: # lol
        logging.warning(" ****************************************************************** ")
        logging.warning(" ****************************************************************** ")
        logging.warning(" **** WARNING **** ALL ANALYSIS RESULTS IN ALERTS **** WARNING **** ")
        logging.warning(" ****************************************************************** ")
        logging.warning(" ****************************************************************** ")

    # warn if timezone is not UTC
    #if time.strftime("%z") != "+0000":
        #logging.warning("Timezone is not UTC. All ACE systems in a cluster should be in UTC.")

    # we can globally disable semaphores with this flag
    SEMAPHORES_ENABLED = CONFIG.getboolean('global', 'enable_semaphores')

    # some settings can be set to PROMPT
    for section in CONFIG.sections():
        for (name, value) in CONFIG.items(section):
            if value == 'PROMPT':
                CONFIG.set(section, name, getpass("Enter the value for {0}:{1}: ".format(section, name)))

    # make sure we've got the ca chain for SSL certs
    CA_CHAIN_PATH = os.path.join(SAQ_HOME, CONFIG['SSL']['ca_chain_path'])

    # initialize the database connection
    initialize_database()

    # initialize fallback semaphores
    #initialize_fallback_semaphores()

    # XXX get rid of this
    try:
        maliciousdir = CONFIG.get("global", "malicious")
    except:
        maliciousdir = "malicious"

    STATS_DIR = os.path.join(DATA_DIR, 'stats')
    MODULE_STATS_DIR = os.path.join(STATS_DIR, 'modules')

    # make sure some key directories exists
    for dir_path in [ 
        os.path.join(DATA_DIR, CONFIG['global']['node']),
        os.path.join(DATA_DIR, 'review', 'rfc822'),
        os.path.join(DATA_DIR, 'review', 'misc'),
        os.path.join(DATA_DIR, CONFIG['global']['error_reporting_dir']),
        STATS_DIR,
        MODULE_STATS_DIR,
        os.path.join(STATS_DIR, 'brocess'), # get rid of this
        os.path.join(STATS_DIR, 'metrics'),
        os.path.join(DATA_DIR, CONFIG['splunk_logging']['splunk_log_dir']),
        os.path.join(DATA_DIR, CONFIG['elk_logging']['elk_log_dir']),
        os.path.join(TEMP_DIR),
        SERVICES_DIR,
        os.path.join(DATA_DIR, CONFIG['collection']['persistence_dir']),
        os.path.join(DATA_DIR, CONFIG['collection']['incoming_dir']),
        DAEMON_DIR, ]: 
        try:
            os.makedirs(dir_path)
        except Exception as e:
            logging.error("unable to create required directory {}: {}".format(dir_path, str(e)))
            sys.exit(1)

    # clear out any proxy environment variables if they exist
    for proxy_key in [ 'http_proxy', 'https_proxy', 'ftp_proxy' ]:
        if proxy_key in os.environ:
            logging.debug("removing proxy environment variable for {}".format(proxy_key))
            del os.environ[proxy_key]
        if proxy_key.upper() in os.environ:
            logging.debug("removing proxy environment variable for {}".format(proxy_key.upper()))
            del os.environ[proxy_key.upper()]

    # load any additional proxies specified in the config sections proxy_*
    for section in CONFIG.keys():
        if section.startswith('proxy_'):
            proxy_name = section[len('proxy_'):]
            OTHER_PROXIES[proxy_name] = {}
            for proxy_key in [ 'http', 'https' ]:
                if CONFIG[section]['host'] and CONFIG[section]['port'] and CONFIG[section]['transport']:
                    if 'user' in CONFIG[section] and 'password' in CONFIG[section] \
                    and CONFIG[section]['user'] and CONFIG[section]['password']:
                        OTHER_PROXIES[proxy_name][proxy_key] = '{}://{}:{}@{}:{}'.format(
                        CONFIG[section]['transport'], 
                        urllib.parse.quote_plus(CONFIG[section]['user']), 
                        urllib.parse.quote_plus(CONFIG[section]['password']), 
                        CONFIG[section]['host'], 
                        CONFIG[section]['port'])
                    else:
                        OTHER_PROXIES[proxy_name][proxy_key] = '{}://{}:{}'.format(
                        CONFIG[section]['transport'], CONFIG[section]['host'], CONFIG[section]['port'])

    # load global constants
    import iptools
    
    MANAGED_NETWORKS = []
    for cidr in CONFIG['network_configuration']['managed_networks'].split(','):
        try:
            if cidr:
                MANAGED_NETWORKS.append(iptools.IpRange(cidr.strip()))
        except Exception as e:
            logging.error("invalid managed network {}: {}".format(cidr, str(e)))

    # are we running as a daemon?
    if args:
        DAEMON_MODE = args.daemon

    # make sure we've got the automation user set up
    #initialize_automation_user()

    # initialize other systems
    #initialize_message_system()

    logging.debug("SAQ initialized")
