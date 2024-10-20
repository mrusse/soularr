import math
import os
import json
from applications import Applications
from pyarr.types import JsonObject

class Arrs(Applications):
    def __init__(
            self,
            type: str,
            host_url: str,
            api_key: str,
            download_dir: str,
            current_page_file_path,
            accepted_formats: list[str],
            accepted_countries: list[str],
            title_blacklist: list[str],
            page_size: int,
            search_type: str,
            prepend_creator: bool,
            remove_wanted_on_failure: bool
        ) -> None:
        super().__init__(type, host_url, api_key, download_dir)
        self.current_page_file_path = current_page_file_path
        self.type = type
        self.accepted_formats = accepted_formats
        self.accepted_countries = accepted_countries
        self.title_blacklist = title_blacklist
        self.page_size = page_size
        self.search_type = search_type
        self.prepend_creator = prepend_creator
        self.remove_wanted_on_failure = remove_wanted_on_failure

    def get_wanted(self, page: int = 1) -> JsonObject:
        raise NotImplementedError(f"get_wanted must be implemented in {self.__class__.__name__}")
    
    def get_title(self, release: JsonObject) -> str:
        raise NotImplementedError(f"get_title must be implemented in {self.__class__.__name__}")
    
    def retag_file(self, release_name: str, filename: str, path: str, folder: dict) -> None:
        raise NotImplementedError(f"retag_file must be implemented in {self.__class__.__name__}")
    
    def import_downloads(self, creator_folders: list[str]) -> None:
        raise NotImplementedError(f"import_downloads must be implemented in {self.__class__.__name__}")

    def is_format_accepted(self, format: str) -> bool:
        return format in self.accepted_formats
    
    def is_blacklisted(self, title: str) -> bool:
        for word in self.title_blacklist:
            if word != '' and word in title.lower():
                print(f"Skipping {title} due to blacklisted word: {word}")
                return True
        return False
    
    def get_current_pages(self) -> dict:
        if os.path.exists(self.current_page_file_path):
            try:
                with open(self.current_page_file_path, 'r') as file:
                    return json.load(file)
            except json.JSONDecodeError:
                pass
        else:
            with open(self.current_page_file_path, 'w') as file:
                json.dump({"lidarr": 1, "readarr": 1}, file)

        return {"lidarr": 1, "readarr": 1}
        
    def update_current_page(self, data: dict) -> None:
        with open(self.current_page_file_path, 'w') as file:
                json.dump(data, file)
    
    def get_wanted_records(self) -> list[JsonObject]:
        wanted: JsonObject = self.get_wanted()
        total_wanted: int = wanted['totalRecords']
        if self.search_type == 'all':
            page = 1
            wanted_records: list[JsonObject] = []
            while len(wanted_records) < total_wanted:
                wanted = self.get_wanted(page)
                wanted_records.extend(wanted['records'])
                page += 1

        elif self.search_type == 'incrementing_page':
            page_data = self.get_current_pages()
            page = page_data[self.type]
            wanted_records = self.get_wanted(page)['records']
            page = 1 if page >= math.ceil(total_wanted / self.page_size) else page + 1
            page_data[self.type] = page
            self.update_current_page(page_data)

        elif self.search_type == 'first_page':
            wanted_records = wanted['records']

        else:
            raise ValueError(f'Error: [Search Settings] - search_type = {self.search_type} is not valid.')
        
        return wanted_records
