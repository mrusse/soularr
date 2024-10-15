import os
import sys
import configparser

# import lidarr
# import readarr
# import slskd

class Soularr:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.lock_file_path = "" if self.is_docker() else os.path.join(os.getcwd(), ".soularr.lock")
        self.config_file_path = os.path.join(os.getcwd(), "/data/config.ini") if self.is_docker() else os.path.join(os.getcwd(), "config.ini")
        self.failure_file_path = os.path.join(os.getcwd(), "/data/failure_list.txt") if self.is_docker() else os.path.join(os.getcwd(), "failure_list.txt")
        self.current_page_file_path = os.path.join(os.getcwd(), "/data/.current_page.txt") if self.is_docker() else os.path.join(os.getcwd(), ".current_page.txt")
        self.check_duplicate_instances()
        self.check_config_file(self.config_file_path)



    def is_docker() -> bool:
        return os.getenv('IN_DOCKER') is not None

    def check_config_file(self, path: str) -> None:
        if os.path.exists(path):
            self.config.read(path)
        else:
            if self.is_docker():
                print("Config file does not exist! Please mount \"/data\" and place your \"config.ini\" file there.")
            else:
                print("Config file does not exist! Please place it in the working directory.")
            print("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")
            if os.path.exists(self.lock_file_path) and not self.is_docker():
                os.remove(self.lock_file_path)
            sys.exit(0)

    def check_duplicate_instances(self) -> None:
        if os.path.exists(self.lock_file_path) and not self.is_docker():
            print("Soularr instance is already running.")
            sys.exit(1)


if __name__ == "__main__":
    # lidarr.Lidarr("http://localhost:8686", )
    # TODO
    soularr = Soularr()
    