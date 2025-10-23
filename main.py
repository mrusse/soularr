import logging
import os
import sys
import traceback
import slskd_api
from pyarr import LidarrAPI

from argparser import SoularrArgParser
from config import SoularrConfig
from soularr import Soularr
from soularr_types import Record, map_raw_record_to_record
from utils import (MISSING, is_docker, logger, setup_logging)

if __name__ == "__main__":

    setup_logging()

    soularr_args = SoularrArgParser()

    if not is_docker() and os.path.exists(soularr_args.get_lock_file_path()) and soularr_args.args.lock_file:
        logger.info(f"Soularr instance is already running.")
        sys.exit(1)

    lock_file_path = soularr_args.get_lock_file_path()

    try:
        if not is_docker() and soularr_args.args.lock_file:
            with open(soularr_args.get_lock_file_path(), "w") as lock_file:
                lock_file.write("locked")

        # Disable interpolation to make storing logging formats in the config file much easier
        soularr_config = SoularrConfig(soularr_args)

        slskd = slskd_api.SlskdClient(host=soularr_config.get_slskd_host_url(), api_key=soularr_config.get_slskd_api_key(), url_base=soularr_config.get_slskd_url_base())
        lidarr = LidarrAPI(soularr_config.get_lidarr_host_url(), soularr_config.get_lidarr_api_key())

        soularr = Soularr(lidarr=lidarr, slskd=slskd, arg_parser=soularr_args, soularr_config=soularr_config)

        # Verify connections to Slskd and Lidarr
        try:
            system_status = lidarr.get_system_status()
            logger.info(f"Connected to Lidarr version {system_status.get('version', 'unknown')}")
        except Exception as ex:
            logger.error(f"Could not connect to Lidarr at {soularr_config.get_lidarr_host_url()}: {ex}")
            logger.error("Exiting...")
            sys.exit(0)

        try:
            version = slskd.application.version()
            logger.info(f"Connected to Slskd version {version}")
        except Exception as ex:
            logger.error(f"Could not connect to Slskd at {soularr_config.get_slskd_host_url()}: {ex}")
            logger.error("Exiting...")
            sys.exit(0)

        # validate this directory exists before starting.
        slskd_download_dir = soularr_config.get_slskd_download_dir()
        if not os.path.isdir(slskd_download_dir):
            logger.error(f"Slskd download directory does not exist: {slskd_download_dir}")
            sys.exit(1)
        else:
            logger.info(f"Using Slskd download directory: {slskd_download_dir}")

        wanted_records = []
        try:
            for source in soularr_config.get_search_sources():
                logging.debug(f'Getting records from {source}')
                raw_records = soularr.get_records(source == MISSING)
                records = [map_raw_record_to_record(record) for record in raw_records]
                logging.info(f'Found {len(records)} records from source "{source}" search')
                wanted_records.extend(records)
        except ValueError as ex:
            logger.error(f'An error occurred: {ex}')
            logger.error('Exiting...')
            sys.exit(0)

        if len(wanted_records) > 0:
            try:
                failed = soularr.grab_most_wanted(wanted_records)
            except Exception:
                logger.error(traceback.format_exc())
                logger.error("\n Fatal error! Exiting...")

                if os.path.exists(lock_file_path) and not is_docker():
                    os.remove(lock_file_path)
                sys.exit(0)
            if failed == 0:
                logger.info("Soularr finished. Exiting...")
                slskd.transfers.remove_completed_downloads()
            else:
                if soularr_config.get_remove_wanted_on_failure():
                    logger.info(f"Failed to find a match for '{failed}' release(s) in the search results. View 'failure_list.txt' for list of failed albums.")
                else:
                    logger.info(f"Failed to find a match for '{failed}' release(s) in the search results and are still wanted.")
                slskd.transfers.remove_completed_downloads()
        else:
            logger.info("No releases wanted. Exiting...")

    finally:
        # Remove the lock file after activity is done
        if os.path.exists(lock_file_path) and not is_docker():
            os.remove(lock_file_path)
