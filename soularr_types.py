from dataclasses import dataclass, field, is_dataclass, asdict
import json
from typing import Any, List, Optional

class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if is_dataclass(o):
            return asdict(o)
        return super().default(o)
    
@dataclass
class Media:
    mediumNumber: int
    mediumName: str
    mediumFormat: str

@dataclass
class Release:
    id: int
    albumId: int
    foreignReleaseId: str
    title: str
    status: str
    duration: int
    trackCount: int
    media: List[Media]
    mediumCount: int
    country: List[str]
    label: List[str]
    format: str
    monitored: bool

@dataclass
class Ratings:
    votes: int
    value: int

@dataclass
class Link:
    url: str
    name: str

@dataclass
class Artist:
    status: str
    ended: bool
    artistName: str
    foreignArtistId: str
    tadbId: int
    discogsId: int
    artistType: str
    disambiguation: str
    links: List[Link]
    nextAlbum: Optional[Any]
    lastAlbum: Optional[Any]
    images: List[Any]
    path: str
    qualityProfileId: int
    metadataProfileId: int
    monitored: bool
    monitorNewItems: str
    genres: List[Any]
    cleanName: str
    sortName: str
    tags: List[int]
    added: str
    ratings: Ratings
    id: int

@dataclass
class Image:
    url: str
    coverType: str
    extension: str
    remoteUrl: str

@dataclass
class Statistics:
    trackFileCount: int
    trackCount: int
    totalTrackCount: int
    sizeOnDisk: int
    percentOfTracks: int

@dataclass
class Record:
    title: str
    disambiguation: str
    overview: str
    artistId: int
    foreignAlbumId: str
    monitored: bool
    anyReleaseOk: bool
    profileId: int
    duration: int
    albumType: str
    secondaryTypes: List[Any]
    mediumCount: int
    ratings: Ratings
    releaseDate: str
    releases: List[Release]
    genres: List[Any]
    media: List[Media]
    artist: Artist
    images: List[Image]
    links: List[Link]
    statistics: Statistics
    id: int
    extra: dict = field(default_factory=dict)

@dataclass
class Track:
    artistId: int
    foreignTrackId: str
    foreignRecordingId: str
    trackFileId: int
    albumId: int
    explicit: bool
    absoluteTrackNumber: int
    trackNumber: str
    title: str
    duration: int
    mediumNumber: int
    hasFile: bool
    ratings: Ratings
    id: int

@dataclass
class SlskdSearch:
    fileCount: int
    id: str
    isComplete: bool
    lockedFileCount: int
    responseCount: int
    responses: list
    searchText: str
    startedAt: str
    state: str
    token: int

@dataclass
class SlskFileInfo:
    code: int
    filename: str
    size: int
    isLocked: bool
    length: Optional[int] = None
    extension: Optional[str] = ""
    bitRate: Optional[int] = None
    bitDepth: Optional[int] = None
    sampleRate: Optional[int] = None
    isVariableBitRate: Optional[bool] = None


@dataclass
class SlskUserUploadInfo:
    username: str
    token: int
    fileCount: int
    files: List[SlskFileInfo]
    hasFreeUploadSlot: bool
    lockedFileCount: int
    lockedFiles: List[str]
    queueLength: int
    uploadSpeed: int


@dataclass
class SlskAttribute:
    type: str
    value: float
@dataclass
class SlskFileEntry:
    filename: str
    extension: str
    size: int
    code: int
    bitDepth: Optional[int] = None
    bitRate: Optional[int] = None
    length: Optional[float] = None
    sampleRate: Optional[int] = None
    attributes: List[SlskAttribute] = field(default_factory=list)
    attributeCount: Optional[int] = 0
    isVariableBitRate: Optional[bool] = None
@dataclass
class SlskDirectory:
    name: str
    fileCount: int
    files: List[SlskFileEntry]

@dataclass
class GrabItem:
    artist_name: str
    release: Release
    dir: str
    discnumber: int
    username: str
    directory: SlskDirectory

class types:
    Media = Media
    Release = Release
    Ratings = Ratings
    Link = Link
    Artist = Artist
    Image = Image
    Statistics = Statistics
    Record = Record
    Track = Track

def map_raw_record_to_record(raw_record: dict) -> Record:
    """
    Recursively map a raw record dict to a Record dataclass instance.
    """
    def map_media_list(media_list):
        return [Media(**media) for media in media_list]

    def map_release_list(release_list):
        return [Release(
            media=map_media_list(release.get('media', [])),
            **{k: v for k, v in release.items() if k != 'media'}
        ) for release in release_list]

    def map_link_list(link_list):
        return [Link(**link) for link in link_list]

    def map_image_list(image_list):
        return [Image(**image) for image in image_list]

    def map_ratings(ratings):
        return Ratings(**ratings) if ratings else Ratings(votes=0, value=0)

    def map_statistics(statistics):
        return Statistics(**statistics) if statistics else Statistics(trackFileCount=0, trackCount=0, totalTrackCount=0, sizeOnDisk=0, percentOfTracks=0)

    def map_artist(artist):
        return Artist(
            links=map_link_list(artist.get('links', [])),
            images=artist.get('images', []),
            ratings=map_ratings(artist.get('ratings', {})),
            **{k: v for k, v in artist.items() if k not in ['links', 'images', 'ratings']}
        )
    
    known_fields = {
        'title', 'disambiguation', 'overview', 'artistId', 'foreignAlbumId', 'monitored', 'anyReleaseOk',
        'profileId', 'duration', 'albumType', 'secondaryTypes', 'mediumCount', 'ratings', 'releaseDate',
        'releases', 'genres', 'media', 'artist', 'images', 'links', 'statistics', 'id'
    }
    extra = {k: v for k, v in raw_record.items() if k not in known_fields}
    return Record(
        ratings=map_ratings(raw_record.get('ratings', {})),
        releases=map_release_list(raw_record.get('releases', [])),
        media=map_media_list(raw_record.get('media', [])),
        artist=map_artist(raw_record.get('artist', {})),
        images=map_image_list(raw_record.get('images', [])),
        links=map_link_list(raw_record.get('links', [])),
        statistics=map_statistics(raw_record.get('statistics', {})),
        extra=extra, # Store any extra fields not defined in the dataclass
        **{k: v for k, v in raw_record.items() if k in known_fields and k not in ['ratings', 'releases', 'media', 'artist', 'images', 'links', 'statistics']}
    )

def map_raw_track_to_track(raw_track: dict) -> Track:
    """
    Map a raw track dict to a Track dataclass instance, including nested Ratings.
    """
    ratings = raw_track.get('ratings', {})
    return Track(
        ratings=Ratings(**ratings) if ratings else Ratings(votes=0, value=0),
        **{k: v for k, v in raw_track.items() if k != 'ratings'}
    )

def map_raw_user_upload_info_to_user_upload_info(raw_info: dict) -> SlskUserUploadInfo:
    """
    Map a raw user upload info dict to a SlskUserUploadInfo dataclass instance, including nested SlskFileInfo objects.
    """
    files = raw_info.get('files', [])
    mapped_files = [SlskFileInfo(**file) for file in files]
    return SlskUserUploadInfo(
        files=mapped_files,
        **{k: v for k, v in raw_info.items() if k != 'files'}
    )

def map_raw_slskd_dir_to_dir(raw_dir: dict) -> SlskDirectory:
    """
    Map a raw album dict to a SlskDirectory dataclass instance, including nested SlskFileEntry and SlskAttribute objects.
    """
    def map_attribute_list(attr_list):
        return [SlskAttribute(**attr) for attr in attr_list]

    def map_file_entry_list(file_list):
        return [SlskFileEntry(
            attributes=map_attribute_list(file.get('attributes', [])),
            **{k: v for k, v in file.items() if k != 'attributes'}
        ) for file in file_list]

    return SlskDirectory(
        files=map_file_entry_list(raw_dir.get('files', [])),
        **{k: v for k, v in raw_dir.items() if k != 'files'}
    )
