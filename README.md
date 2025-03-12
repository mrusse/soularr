![banner](https://raw.githubusercontent.com/mrusse/soularr/refs/heads/main/resources/banner.png)

<h1 align="center">Soularr</h1>
<p align="center">
  A Python script that connects Lidarr with Soulseek!
</p>

<p align="center">
  <a href="https://discord.gg/EznhgYBayN">
    <img src="https://img.shields.io/discord/1292895470301220894?label=Discord&logo=discord&style=for-the-badge&cacheSeconds=60" alt="Join our Discord">
  </a>
</p>

# About

Soularr reads all of your "wanted" albums/artists from Lidarr and downloads them using Slskd. It uses the libraries: [pyarr](https://github.com/totaldebug/pyarr) and [slskd-api](https://github.com/bigoulours/slskd-python-api) to make this happen. View the demo below!

![Soularr_small](https://github.com/user-attachments/assets/15c47a82-ddf2-40e3-b143-2ad7f570730f)

After the downloads are complete in Slskd the script will tell Lidarr to import the downloaded files, making it a truly hands off process.

# Setup

## Install and configure Lidarr and Slskd

**Lidarr**
[https://lidarr.audio/](https://lidarr.audio/)

Make sure Lidarr can see your Slskd download directory, if you are running Lidarr in a Docker container you may need to mount the directory. You will then need add it to your config (see "download_dir" under "Lidarr" in the example config).

**Slskd**
[https://github.com/slskd/slskd](https://github.com/slskd/slskd)

The script requires an api key from Slskd. Take a look at their [docs](https://github.com/slskd/slskd/blob/master/docs/config.md#authentication) on how to set it up (all you have to do is add it to the yml file under `web, authentication, api_keys, my_api_key`).

## Docker

The best way to run the script is through Docker. A Docker image is available through [dockerhub](https://hub.docker.com/r/mrusse08/soularr).

Assuming, your user and group is `1000:1000` and that you have a directory structure similar to the following:

```bash
/
├── Media
│   ├── Downloads
│   ├── Music
│   └── slskd_downloads
└── Containers
    ├── lidarr
    ├── slskd
    └── soularr
```

Where `Downloads` could be any music download directory, `slskd_downloads` is your slskd download directory, and finally `Music` is the location for you music files then an example docker run command might be:

```shell
docker run -d \
  --name soularr \
  --restart unless-stopped \
  --hostname soularr \
  -e TZ=ETC/UTC \
  -e SCRIPT_INTERVAL=300 \
  -v /Media/slskd_downloads:/downloads \
  -v /Containers/soularr:/data \
  --user 1000:1000 \
  mrusse08/soularr:latest
```

Or you can also set it up with the provided [Docker Compose](https://github.com/mrusse/soularr/blob/main/docker-compose.yml).

```yml
services:
  soularr:
    image: mrusse08/soularr:latest
    container_name: soularr
    hostname: soularr
  user: 1000:1000 # this should be set to your UID and GID, which can be determined via `id -u` and `id -g`, respectively
    environment:
      - TZ=Etc/UTC
      - SCRIPT_INTERVAL=300 # Script interval in seconds
    volumes:
      # "You can set /downloads to whatever you want but will then need to change the Slskd download dir in your config file"
      - /Media/slskd_downloads:/downloads
      # Select where you are storing your config file.
      # Leave "/data" since thats where the script expects the config file to be
      - /Containers/soularr:/data
    restart: unless-stopped
```

Note: You **must** edit both volumes in the docker compose above.

- `/path/to/slskd/downloads:/downloads`

  - This is where you put your Slskd downloads path.

  - You can point it to whatever dir you want but make sure to put the same dir in your config file under `[Slskd] -> download_dir`.

  - For example you could leave it as `/downloads` then in your config your entry would be `download_dir = /downloads`.

- `/path/to/config/dir:/data`

  - This is where put the path you are storing your config file. It must point to `/data`.

You can also edit `SCRIPT_INTERVAL` to choose how often (in seconds) you want the script to run (default is every 300 seconds). Another thing to note is that by default the user is set to appropriate user on your system. If you wish to edit this change `user: 1000:1000` in the Docker compose to whatever you prefer. You can determine the user via the command `id -u` and the group vi `id -g`.

It is important that `lidarr` and `slskd` agree on the user/group. If they do not agree then it is unlikely you will have successful imports. Also, it is important to note that lidarr will need access to the downloads directory of slskd.

For a more complete example see the compose file bellow which contains `lidarr`, `slskd`, and `soularr`:

```yml
services
  lidarr:
    image: ghcr.io/hotio/lidarr:latest
    container_name: lidarr
    hostname: lidarr
    environment:
      - TZ=ETC/UTC
      - PUID=1000
      - PGID=1000
    volumes:
      - /Containers/lidarr:/config
      - /Media:/data
    ports:
      - 8686:8686
    restart: unless-stopped

  slskd:
    image: slskd/slskd
    container_name: slskd
    hostname: slskd
    user: 1000:1000
    environment:
      - TZ=ETC/UTC
      - SLSKD_REMOTE_CONFIGURATION=true
    ports:
      - 5030:5030
      - 5031:5031
      - 50300:50300
    volumes:
      - /Containers/slskd:/app
      - /Media:/data
    restart: unless-stopped

  soularr:
    image: mrusse08/soularr:latest
    container_name: soularr
    hostname: soularr
    user: 1000:1000
    environment:
      - TZ=ETC/UTC
      - SCRIPT_INTERVAL=300
    volumes:
      - /Media/slskd_downloads:/downloads
      - /Container/soularr:/data
    restart: unless-stopped
```

## Configure your config file

The config file has a bunch of different settings that affect how the script runs. Any lists in the config such as "accepted_countries" need to be comma separated with no spaces (e.g. `","` not `" , "` or `" ,"`).

Given the directory structure above you can use the following configuration

**Example config:**

```ini
[Lidarr]
api_key = yourlidarrapikeygoeshere   # get this from lidarr settings > general > security > API Key
host_url = http://lidarr:8686        # A safe bet would be to use the url you use to connect manually
download_dir = /data/slskd_downloads # this should be the path to slskd downloads in the lidarr container

[Slskd]
api_key = yourslskdapikeygoeshere    # generate this key manually see documentation above
host_url = http://slskd:5030         # A safe bet would be to use the url that you use to manually connect to slskd
url_base = /
download_dir = /downloads            # slskd download directory from within the slskd container
delete_searches = False              # delete the search after each soularr search
stalled_timeout = 3600               # Maximum time (in seconds) that the script will wait for downloads to complete.
                                     # This is used to prevent the script from running forever due to a stalled download.
                                     # Defaults to 1 hour.

[Release Settings]
use_most_common_tracknum = True      # Selects the release with the most common amount of tracks out of all the releases.
allow_multi_disc = True
accepted_countries = Europe,Japan,United Kingdom,United States,[Worldwide],Australia,Canada # See full list of countries below.
accepted_formats = CD,Digital Media,Vinyl      # See full list of formats below.

[Search Settings]
search_timeout = 5000
maximum_peer_queue = 50
minimum_peer_upload_speed = 0        # Min upload speed in bit/s
minimum_filename_match_ratio = 0.5   # Min match ratio accepted when comparing lidarr track names to soulseek filenames.
allowed_filetypes = flac 24/192,flac 16/44.1,flac,mp3 320,mp3 # Specify the file types you prefer from most to least. As well as their attributes such as bitrate / samplerate / bitdepth.
                                                              # For flacs you can choose the bitdepth/samplerate. And for mp3s the bitrate.
                                                              # If you do not care about the specific quality you can still just put "flac" or "mp3".
                                                              # Soularr will then just look at the filetype and ignore file attributes.
ignored_users = User1,User2,Fred,Bob
search_for_tracks = True            # Set to False if you only want to search for complete albums
album_prepend_artist = False        # Set to True if you want to add the artist's name to the beginning of the search for albums
track_prepend_artist = True
search_type = incrementing_page     # Valid search types: all || incrementing_page || first_page
                                    # "all" will search for every wanted record everytime soularr is run.
                                    # "incrementing_page" will start with the first page and increment to the next on each run.
                                    # "first_page" will repeatedly search the first page.
                                    # If using the search type "first_page" remove_wanted_on_failure should be enabled.
number_of_albums_to_grab = 10       # How mancy records to grab each run, must be a number between 1 - 2,147,483,647
remove_wanted_on_failure = False    # Unmonitors the album if Soularr can't find it and places it in "failure_list.txt".
                                    # Failed albums can be re monitored by filtering "Unmonitored" in the Lidarr wanted list.
title_blacklist = Word1,word2       # Comma separated list of words that can't be in the title of albums or tracks. Case insensitive.
search_source = missing             # Lidarr source to use for searching. Accepted values are "missing" or "cutoff_unmet".
                                    # Default value is "missing".

[Logging]
# These options are passed into the logger's basicConfig() method as-is.
# This means, if you're familiar with Python's logging module, you can configure
# the logger with options beyond what's listed here by default.
# For more information on available options  --  https://docs.python.org/3/library/logging.html#logging.basicConfig
level = INFO                       # Logging level valid values are INFO, WARN, DEBUG, ERROR, CRITICAL
format = [%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s # Format of log message  --  https://docs.python.org/3/library/logging.html#logrecord-attributes
datefmt = %Y-%m-%dT%H:%M:%S%z      # Format of datetimes  --  https://docs.python.org/3/library/time.html#time.strftime
```

[Full list of countries from Musicbrainz.](https://musicbrainz.org/doc/Release/Country)

[Full list of formats (also from Musicbrainz but for some reason they don't have a nice list)](https://pastebin.com/raw/pzGVUgaE)

An [example config](https://github.com/mrusse/soularr/blob/main/config.ini) is included in the repo.

## Running Manually

Install the requirements:

```bash
python -m pip install -r requirements.txt
```

You can simply run the script with:

```bash
python soularr.py
```

Note: the `config.ini` file needs to be in the same directory as `soularr.py`.

### Scheduling the script

Even if you are not using Docker you can still schedule the script. I have included an example bash script below that can be scheduled using a [cron job](https://crontab.guru/every-5-minutes).

```bash
#!/bin/bash
cd /path/to/soularr/python/script

dt=$(date '+%d/%m/%Y %H:%M:%S');
echo "Starting Soularr! $dt"

if ps aux | grep "[s]oularr.py" > /dev/null; then
    echo "Soularr is already running. Exiting..."
else
    python soularr.py
fi
```

**Example cron job setup:**

Edit crontab file with

```bash
crontab -e
```

Then enter in your schedule followed by the command. For example:

```cron
*/5 * * * * /path/to/run.sh
```

This would run the bash script every 5 minutes.

All of this is focused on Linux but the Python script runs fine on Windows as well. You can use things like the [Windows Task Scheduler](https://en.wikipedia.org/wiki/Windows_Task_Scheduler) to perform similar scheduling operations.

## Logging

There are some very basic options for logging found under the `[Logging]` section of the `config.ini` file. The defaults
should be sensible for a typical logging scenario, but are still somewhat opinionated. Some users may not like how the
log messages are formatted and would prefer a much simpler output than what is provided by default.

For example, if you want the logs to only show the message and none of the other detailed information, edit the
`[Logging]` section's `format` property to look like this:

```ini
[Logging]
format = %(message)s
```

For more information on the options available for logging, including more options for changing how the messages are
formatted, see the comments in the `[Logging]` section from the [example config.ini](#configure-your-config-file).

### Log to a File

Currently, the logs are only output to stdout which should be suitable for most users who just want a basic and simple
set up for Soularr. For users running Soularr as a long-running process, or as part of a cronjob, or for any reason where
logging to a file is desired, normal command-line tools can be used without needing to touch the logger's configuration.

For example, the `tee` command on Linux and MacOS can be used to allow Soularr to log its output to both stdout and a
file of your choosing (here the file `soularr.log` is used, but it can be any file you want):

```sh
python soularr.py 2>&1 | tee -a soularr.log
```

Or on Windows PowerShell using the similar `Tee-Object` cmdlet:

```powershell
python soularr.py 2>&1 | Tee-Object -FilePath soularr.log -Append
```

### View logs in WebUI

[EricH9958](https://github.com/EricH9958) has made a log viewer that lets you monitor the Soularr logs in your browser! Check his repo out here:

[https://github.com/EricH9958/Soularr-Dashboard](https://github.com/EricH9958/Soularr-Dashboard)

### Advanced Logging Usage

The current logging setup for Soularr is *very* simple and only allows for the most basic configuration options
provided by [Python's builtin logging module](https://docs.python.org/3/library/logging.html). Logging was kept simple
to avoid over-complicating things, and it seems like the desire for more advanced logging capabilities is currently
quite low.

**If you would like more advanced logging configuration options to be implemented** (such as configuring filters,
formatters, handlers, additional streams, and multi-logger setups), consider submitting a feature request in
[the official discord](https://discord.gg/EznhgYBayN) or [submitting an Issue in the GitHub repository itself](https://github.com/mrusse/soularr/issues).

##

<p align="center">
  <a href='https://ko-fi.com/mrusse' target='_blank'><img height='35' style='border:0px;height:46px;' src='https://az743702.vo.msecnd.net/cdn/kofi3.png?v=0' border='0' alt='Buy Me a Coffee at ko-fi.com' /></a>
</p>
