import os
from arrs import Arrs
from pyarr.types import JsonObject

class Readarr(Arrs):
    def __init__(
            self,
            host_url: str,
            api_key: str,
            download_dir: str,
            current_page_file_path: str,
            title_blacklist: list[str],
            number_of_books_to_grab: int,
            search_type: str,
            prepend_creator: bool,
            remove_wanted_on_failure: bool
        ) -> None:
        super().__init__('readarr', host_url, api_key, download_dir, current_page_file_path, title_blacklist, number_of_books_to_grab, search_type, prepend_creator, remove_wanted_on_failure)

    def get_wanted(self, page: int = 1) -> JsonObject:
        return self.readarr.get_missing(page=page, page_size=self.page_size, sort_dir='ascending',sort_key='title')
    
    def get_command(self, id: int) -> dict:
        return self.readarr.get_command(id)
    
    def retag_file(self, release_name: str, filename: str, path: str, folder: dict) -> None:
        # TODO: Likely needed for audiobooks, but I don't use readarr for audiobooks so idk
        pass

    def import_downloads(self, creator_folders: list[str]) -> None:
        import_commands: list[JsonObject] = []
        for creator_folder in creator_folders:
            task = self.readarr.post_command(name = 'DownloadedBooksScan', path = os.path.join(self.download_dir, creator_folder))
            import_commands.append(task)
            print(f"Starting Readarr import for: {creator_folder} ID: {task['id']}")
        self.monitor_import_commands(import_commands)
        for task in import_commands:
            self.process_import_task(self.readarr.get_command(task['id']))

    def grab_book(self, record: JsonObject) -> tuple[str, str]:
        book = self.readarr.get_book(record['id'])
        book_title = book['title']
        author_name = book['author']['authorName']
        if self.is_blacklisted(book_title):
            return (None, author_name)
        query = f"{author_name} {book_title}" if self.prepend_creator or len(book_title) == 1 else book_title
        return (query, book_title)

    # TODO