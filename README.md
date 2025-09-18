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

The best way to run the script is through Docker. A Docker image is available through [ghcr.io](https://github.com/mrusse/soularr/pkgs/container/soularr) and [dockerhub](https://hub.docker.com/r/mrusse08/soularr).

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
services:
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
# Get from Lidarr: Settings > General > Security
api_key = yourlidarrapikeygoeshere
# URL Lidarr uses (e.g., what you use in your browser)
host_url = http://lidarr:8686
# Path to slskd downloads inside the Lidarr container
download_dir = /data/slskd_downloads
# If true, Lidarr won't auto-import from Slskd
disable_sync = False

[Slskd]
# Create manually (see docs)
api_key = yourslskdapikeygoeshere
# URL Slskd uses
host_url = http://slskd:5030
url_base = /
# Download path inside Slskd container
download_dir = /downloads
# Delete search after Soularr runs
delete_searches = False
# Max seconds to wait for downloads (prevents infinite hangs)
stalled_timeout = 3600

[Release Settings]
# Pick release with most common track count
use_most_common_tracknum = True
allow_multi_disc = True
# Accepted release countries
accepted_countries = Europe,Japan,United Kingdom,United States,[Worldwide],Australia,Canada
# Don't check the region of the release
skip_region_check = False 
# Accepted formats
accepted_formats = CD,Digital Media,Vinyl

[Search Settings]
search_timeout = 5000
maximum_peer_queue = 50
# Minimum upload speed (bits/sec)
minimum_peer_upload_speed = 0
# Minimum match ratio between Lidarr track and Soulseek filename
minimum_filename_match_ratio = 0.8
# Preferred file types and qualities (most to least preferred)
# Use "flac" or "mp3" to ignore quality details
allowed_filetypes = flac 24/192,flac 16/44.1,flac,mp3 320,mp3
ignored_users = User1,User2,Fred,Bob
# Set to False to only search for album titles (Note Soularr does not search for individual tracks, this setting searches for track titles but still tries to match to the full album). 
search_for_tracks = True
# Prepend artist name when searching for albums
album_prepend_artist = False
track_prepend_artist = True
# Search modes: all, incrementing_page, first_page
# "all": search for every wanted record, "first_page": repeatedly searches the first page, "incrementing_page": starts with the first page and increments on each run.
search_type = incrementing_page
# Albums to process per run
number_of_albums_to_grab = 10
# Unmonitor album on failure; logs to failure_list.txt
remove_wanted_on_failure = False
# Blacklist words in album or track titles (case-insensitive)
title_blacklist = Word1,word2
# Lidarr search source: "missing" or "cutoff_unmet"
search_source = missing
# Enable search denylist to skip albums that repeatedly fail
enable_search_denylist = False
# Number of consecutive search failures before denylisting
max_search_failures = 3

[Logging]
# Passed to Python's logging.basicConfig()
# See: https://docs.python.org/3/library/logging.html
level = INFO
format = [%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s
datefmt = %Y-%m-%dT%H:%M:%S%z
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
