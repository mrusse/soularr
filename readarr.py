import os

from pyarr.types import JsonObject

from arrs import Arrs


class Readarr(Arrs):
    """Readarr class for managing book-related operations."""

    def __init__(
            self,
            application_settings: tuple[str, str, str],
            current_page_file_path: str,
            title_blacklist: list[str],
            number_of_books_to_grab: int,
            search_type: str,
            prepend_creator: bool,
            remove_wanted_on_failure: bool,
        ) -> None:
        """Initialize the Readarr class with the given parameters.

        Args:
            application_settings (tuple[str, str, str]): A tuple containing the application settings (host_url, api_key, download_dir).
            current_page_file_path (str): The file path to the current page.
            title_blacklist (list[str]): A list of titles to be blacklisted.
            number_of_books_to_grab (int): The number of books to grab.
            search_type (str): The type of search to be performed.
            prepend_creator (bool): Whether to prepend the creator's name.
            remove_wanted_on_failure (bool): Whether to remove wanted items on failure.

        """
        super().__init__(application_settings, current_page_file_path, title_blacklist, number_of_books_to_grab, search_type, prepend_creator, remove_wanted_on_failure)

    def get_wanted(self, page: int = 1) -> JsonObject:
        """Retrieve the list of wanted books.

        Args:
            page (int, optional): The page number to retrieve. Defaults to 1.

        Returns:
            JsonObject: The JSON object containing the list of wanted books.

        """
        return self.readarr.get_missing(page=page, page_size=self.page_size, sort_dir="ascending",sort_key="title")

    def get_command(self, id: int) -> dict:
        """Retrieve the command with the specified ID.

        Args:
            id (int): The ID of the command to retrieve.

        Returns:
            dict: The command details.

        """
        return self.readarr.get_command(id)

    def retag_file(self, release_name: str, filename: str, path: str, folder: dict) -> None:
        """Retag a file with the given parameters.

        Args:
            release_name (str): The name of the release.
            filename (str): The name of the file.
            path (str): The path to the file.
            folder (dict): The folder details.

        """
        # TODO: Likely needed for audiobooks, but I don't use readarr for audiobooks so idk

    def import_downloads(self, creator_folders: list[str]) -> None:
        """Import downloaded books from the specified creator folders.

        Args:
            creator_folders (list[str]): A list of creator folder names to import downloads from.

        """
        import_commands: list[JsonObject] = []
        for creator_folder in creator_folders:
            task = self.readarr.post_command(name = "DownloadedBooksScan", path = os.path.join(self.download_dir, creator_folder))
            import_commands.append(task)
            print(f"Starting Readarr import for: {creator_folder} ID: {task['id']}")
        self.monitor_import_commands(import_commands)
        for task in import_commands:
            self.process_import_task(self.readarr.get_command(task["id"]))

    def grab_book(self, record: JsonObject) -> tuple[str, str]:
        """Grab a book based on the given record.

        Args:
            record (JsonObject): The JSON object containing the book record.

        Returns:
            tuple[str, str]: A tuple containing the query string and the book title.

        """
        book = self.readarr.get_book(record["id"])
        book_title = book["title"]
        author_name = book["author"]["authorName"]
        if self.is_blacklisted(book_title):
            return (None, author_name)
        query = f"{author_name} {book_title}" if self.prepend_creator or len(book_title) == 1 else book_title
        return (query, book_title)
