import slskd_api
from pyarr import LidarrAPI, ReadarrAPI


class Applications:
    """A class to manage different applications.

    Attributes:
        host_url (str): The URL of the host.
        download_dir (str): The directory where downloads will be stored.
        lidarr (LidarrAPI): The Lidarr API instance.
        readarr (ReadarrAPI): The Readarr API instance.
        slskd (slskd_api.SlskdClient): The Slskd API instance.

    """

    def __init__(self, application: str, application_settings: tuple[str, str, str]) -> None:
        """Initialize the Applications class.

        Args:
            application (str): The type of application (e.g., 'lidarr', 'readarr', 'slskd').
            application_settings (tuple[str, str, str]): A tuple containing the host URL, API key, and download directory.

        """
        host_url, api_key, download_dir = application_settings
        if application == "lidarr":
            self.lidarr = LidarrAPI(host_url, api_key)
        elif application == "readarr":
            self.readarr = ReadarrAPI(host_url, api_key)
        elif application == "slskd":
            self.slskd = slskd_api.SlskdClient(host_url, api_key, "/")
        else:
            raise ValueError(f"Invalid application type: {type}")
        self.host_url = host_url
        self.download_dir = download_dir
