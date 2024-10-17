from arrs import Arrs
from pyarr.types import JsonArray, JsonObject

class Readarr(Arrs):
    def __init__(self: object, host_url: str, api_key: str, download_dir: str, accepted_formats: list[str], accepted_countries: list[str], number_of_books_to_grab: int, page_size: int) -> None:
        super().__init__('readarr', host_url, api_key, download_dir, accepted_formats, accepted_countries, number_of_books_to_grab, page_size)

    def get_wanted(self, page: int = 1) -> JsonObject:
        return self.readarr.get_missing(page=page, page_size=self.page_size, sort_dir='ascending',sort_key='title')

    # TODO