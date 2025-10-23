import configparser
import os
import sys

from argparser import SoularrArgParser
from utils import is_docker, logger


class EnvInterpolation(configparser.ExtendedInterpolation):
    """
    Interpolation which expands environment variables in values.
    Borrowed from https://stackoverflow.com/a/68068943
    """

    def before_read(self, parser, section, option, value):
        value = super().before_read(parser, section, option, value)
        return os.path.expandvars(value)
    
class SoularrConfig:
    def __init__(self, arg_parser: SoularrArgParser):
        self.config = configparser.ConfigParser(interpolation=EnvInterpolation())

        if os.path.exists(arg_parser.get_config_file_path()):
            self.config.read(arg_parser.get_config_file_path())
        else:
            if is_docker():
                logger.error('Config file does not exist! Please mount "/data" and place your "config.ini" file there. Alternatively, pass `--config-dir /directory/of/your/liking` as post arguments to store the config somewhere else.')
                logger.error("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")
            else:
                logger.error("Config file does not exist! Please place it in the working directory. Alternatively, pass `--config-dir /directory/of/your/liking` as post arguments to store the config somewhere else.")
                logger.error("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")
            if os.path.exists(arg_parser.get_lock_file_path()) and not is_docker():
                os.remove(arg_parser.get_lock_file_path())
            sys.exit(0)

    def get_slskd_api_key(self) -> str:
        """Get the Slskd API key from the configuration."""
        return self.config['Slskd']['api_key']

    def get_lidarr_api_key(self) -> str:
        """Get the Lidarr API key from the configuration."""
        return self.config['Lidarr']['api_key']

    def get_lidarr_download_dir(self) -> str:
        """Get the Lidarr download directory path from the configuration."""
        return self.config['Lidarr']['download_dir']

    def get_slskd_download_dir(self) -> str:
        """Get the Slskd download directory path from the configuration."""
        return self.config['Slskd']['download_dir']
        
    def get_lidarr_disable_sync(self) -> bool:
        """Get whether Lidarr sync is disabled from the configuration."""
        return self.config.getboolean('Lidarr', 'disable_sync', fallback=False)

    def get_lidarr_host_url(self) -> str:
        """Get the Lidarr host URL from the configuration."""
        return self.config['Lidarr']['host_url']

    def get_slskd_host_url(self) -> str:
        """Get the Slskd host URL from the configuration."""
        return self.config['Slskd']['host_url']

    def get_slskd_url_base(self) -> str:
        """Get the Slskd URL base from the configuration."""
        return self.config.get('Slskd', 'url_base', fallback='/')

    def get_stalled_timeout(self) -> int:
        """Get the stalled timeout value in seconds from the configuration."""
        return self.config.getint('Slskd', 'stalled_timeout', fallback=3600)

    def get_delete_searches(self) -> bool:
        """Get whether to delete searches from the configuration."""
        return self.config.getboolean('Slskd', 'delete_searches', fallback=True)

    def get_remove_wanted_on_failure(self) -> bool:
        """Get whether to remove wanted items on failure from the configuration."""
        return self.config.getboolean('Search Settings', 'remove_wanted_on_failure', fallback=True)

    def get_enable_search_denylist(self) -> bool:
        """Get whether search denylist is enabled from the configuration."""
        return self.config.getboolean('Search Settings', 'enable_search_denylist', fallback=False)

    def get_max_search_failures(self) -> int:
        """Get the maximum number of search failures allowed from the configuration."""
        return self.config.getint('Search Settings', 'max_search_failures', fallback=3)

    def get_allowed_filetypes(self) -> list[str]:
        """Get the list of allowed filetypes from the configuration."""
        return self.config.get('Search Settings', 'allowed_filetypes', fallback='flac,mp3').split(',')

    def get_ignored_users(self) -> list[str]:
        """Get the list of ignored users from the configuration."""
        return self.config.get('Search Settings', 'ignored_users', fallback='').split(",")

    def get_search_type(self) -> str:
        """Get the search type from the configuration."""
        return self.config.get('Search Settings', 'search_type', fallback='first_page').lower().strip()

    def get_search_source(self) -> str:
        """Get the search source from the configuration."""
        return self.config.get('Search Settings', 'search_source', fallback='MISSING').lower().strip()

    def get_search_sources(self) -> list[str]:
        """Get the list of search sources from the configuration."""
        search_source = self.get_search_source()
        search_sources = [search_source]
        if 'all' in search_sources:
            search_sources = ['missing', 'cutoff_unmet']
        return search_sources

    def get_minimum_match_ratio(self) -> float:
        """Get the minimum filename match ratio from the configuration."""
        return self.config.getfloat('Search Settings', 'minimum_filename_match_ratio', fallback=0.5)

    def get_page_size(self) -> int:
        """Get the number of albums to grab from the configuration."""
        return self.config.getint('Search Settings', 'number_of_albums_to_grab', fallback=10)

    def get_use_most_common_tracknum(self) -> bool:
        """Get whether to use most common track number from the configuration."""
        return self.config.getboolean('Release Settings', 'use_most_common_tracknum', fallback=True)

    def get_allow_multi_disc(self) -> bool:
        """Get whether to allow multi-disc releases from the configuration."""
        return self.config.getboolean('Release Settings', 'allow_multi_disc', fallback=True)

    def get_accepted_countries(self) -> list[str]:
        """Get the list of accepted countries from the configuration."""
        default_accepted_countries = "Europe,Japan,United Kingdom,United States,[Worldwide],Australia,Canada"
        return self.config.get('Release Settings', 'accepted_countries', 
                             fallback=default_accepted_countries).split(",")

    def get_skip_region_check(self) -> bool:
        """Get whether to skip region check from the configuration."""
        return self.config.getboolean('Release Settings', 'skip_region_check', fallback=False)

    def get_accepted_formats(self) -> list[str]:
        """Get the list of accepted formats from the configuration."""
        default_accepted_formats = "CD,Digital Media,Vinyl"
        return self.config.get('Release Settings', 'accepted_formats', 
                             fallback=default_accepted_formats).split(",")
    
    def get_search_timeout(self) -> int:
        """Get the search timeout from the configuration."""
        return self.config.getint('Search Settings', 'search_timeout', fallback=5000)
    
    def get_maximum_peer_queue(self) -> int:
        """Get the maximum peer queue from the configuration."""
        return self.config.getint('Search Settings', 'maximum_peer_queue', fallback=50)
    
    def get_minimum_peer_upload_speed(self) -> int:
        """Get the minimum peer upload speed from the configuration."""
        return self.config.getint('Search Settings', 'minimum_peer_upload_speed', fallback=0)
    
    def get_title_blacklist(self) -> list[str]:
        """Get the title blacklist from the configuration."""
        return self.config.get('Search Settings', 'title_blacklist', fallback='').lower().split(",")

    def get_album_prepend_artist(self) -> bool:
        """Get whether to prepend artist name to album title in searches."""
        return self.config.getboolean('Search Settings', 'album_prepend_artist', fallback=False)
    
    def get_search_for_tracks(self) -> bool:
        """Get whether to search for tracks from the configuration."""
        return self.config.getboolean('Search Settings', 'search_for_tracks', fallback=True)
    
    def get_track_prepend_artist(self) -> bool:
        """Get whether to prepend artist name to track title in searches."""
        return self.config.getboolean('Search Settings', 'track_prepend_artist', fallback=True)