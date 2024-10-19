from arrs import Arrs
from pyarr.types import JsonObject

class Readarr(Arrs):
    def __init__(self: object, host_url: str, api_key: str, download_dir: str, accepted_formats: list[str], accepted_countries: list[str], number_of_books_to_grab: int, page_size: int) -> None:
        super().__init__('readarr', host_url, api_key, download_dir, accepted_formats, accepted_countries, number_of_books_to_grab, page_size)

    def get_wanted(self, page: int = 1) -> JsonObject:
        return self.readarr.get_missing(page=page, page_size=self.page_size, sort_dir='ascending',sort_key='title')
    
    def get_title(self, release: JsonObject) -> str:
        # gotta check if bookId is the right key
        return self.readarr.get_book(albumIds = release['bookId'])['title']
    
    def retag_file(self, release_name: str, filename: str, path: str, folder: dict) -> None:
        # TODO: Likely needed for audiobooks, but I don't use readarr for audiobooks so idk
        pass

    def import_downloads(self, creator_folders: list[str]) -> None:
        # gotta check if DownloadedBooksScan is the right command
        # TODO
        pass

    # TODO