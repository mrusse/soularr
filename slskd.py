import slskd_api

class Slskd:
    def __init__(self, api_key, host_url, download_dir):
        self.slskd = slskd_api.SlskdClient(host_url, api_key, '/')