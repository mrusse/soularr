import logging
import os

#Allows backwards compatibility for users updating an older version of Soularr
#without using the new [Logging] section in the config.ini file.
DEFAULT_LOGGING_CONF = {
    'level': 'INFO',
    'format': '[%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s',
    'datefmt': '%Y-%m-%dT%H:%M:%S%z',
}

logger = logging.getLogger('soularr')

# common variables
MISSING = 'missing'
CUTOFF_UNMET = 'cutoff_unmet'
ALL = 'all'

def setup_logging():
    if 'Logging' in DEFAULT_LOGGING_CONF:
        log_config = DEFAULT_LOGGING_CONF['Logging']
    else:
        log_config = DEFAULT_LOGGING_CONF
    logging.basicConfig(**log_config)   # type: ignore

def is_docker():
    return os.getenv('IN_DOCKER') is not None

def slskd_version_check(version, target="0.22.2"):
    version_tuple = tuple(map(int, version.split('.')[:3]))
    target_tuple = tuple(map(int, target.split('.')[:3]))
    return version_tuple > target_tuple
