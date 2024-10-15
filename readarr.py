from pyarr import ReadarrAPI
from pyarr.types import JsonArray, JsonObject

class Readarr:
    def __init__(self: object, host_url: str, api_key: str, download_dir: str, accepted_formats: list[str]):
        self.readarr = ReadarrAPI(host_url, api_key)
        self.download_dir = download_dir
        self.accepted_formats = accepted_formats

    # TODO