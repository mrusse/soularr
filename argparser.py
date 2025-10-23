import argparse
import os

from utils import is_docker


class SoularrArgParser:
    def __init__(self):
        # Let's allow some overrides to be passed to the script
        self.parser = argparse.ArgumentParser(
            description="""Soularr reads all of your "wanted" albums/artists from Lidarr and downloads them using Slskd"""
        )
        self._add_arguments()
        self.args = self.parser.parse_args()

    def _add_arguments(self):
        default_data_directory = os.getcwd()

        if is_docker():
            default_data_directory = "/data"
        self.parser.add_argument(
            "-c",
            "--config-dir",
            default=default_data_directory,
            const=default_data_directory,
            nargs="?",
            type=str,
            help="Config directory (default: %(default)s)",
        )

        self.parser.add_argument(
            "-v",
            "--var-dir",
            default=default_data_directory,
            const=default_data_directory,
            nargs="?",
            type=str,
            help="Var directory (default: %(default)s)",
        )

        self.parser.add_argument(
            "--no-lock-file",
            action="store_false",
            dest="lock_file",
            default=True,
            help="Disable lock file creation",
        )

    def get_args(self):
        return self.args
    
    def get_lock_file_path(self):
        return os.path.join(self.args.var_dir, ".soularr.lock")
    
    def get_config_file_path(self):
        return os.path.join(self.args.config_dir, "config.ini")
    
    def get_failure_file_path(self):
        return os.path.join(self.args.var_dir, "failure_list.txt")
    
    def get_current_page_file_path(self):
        return os.path.join(self.args.var_dir, ".current_page.txt")
    
    def get_denylist_file_path(self):
        return os.path.join(self.args.var_dir, "search_denylist.json")