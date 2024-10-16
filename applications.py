from pyarr import LidarrAPI, ReadarrAPI
from pyarr.types import JsonObject
import slskd_api

class Applications:
    def __init__(self: object, type: str, host_url: str, api_key: str, download_dir: str):
        if type == 'lidarr':
            self.lidarr = LidarrAPI(host_url, api_key)
        elif type == 'readarr':
            self.readarr = ReadarrAPI(host_url, api_key)
        elif type == 'slskd':
            self.slskd = slskd_api.SlskdClient(host_url, api_key, '/')
        else:
            raise ValueError(f"Invalid application type: {type}")
        self.download_dir = download_dir