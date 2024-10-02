![logo](https://github.com/user-attachments/assets/392a5d30-a34e-4794-8af4-7baae4afff70)

<h1 align="center">Soularr</h1>
<p align="center">
  A Python script that connects Lidarr with Soulseek!
</p>


# About

Soularr reads all of your "wanted" albums/artists from Lidarr and downloads them using Slskd. It uses the libraries: [pyarr](https://github.com/totaldebug/pyarr) and [slskd-api](https://github.com/bigoulours/slskd-python-api) to make this happen. View the demo below!

![Soularr_small](https://github.com/user-attachments/assets/15c47a82-ddf2-40e3-b143-2ad7f570730f)


After the downloads are complete in Slskd the script will tell Lidarr to import the downloaded files, making it a truly hands off process.
# Setup

### Install the requirements:
```
python -m pip install -r requirements.txt
```

### Install and configure Lidarr and Slskd

**Lidarr**
[https://lidarr.audio/](https://lidarr.audio/)

**Slskd**
[https://github.com/slskd/slskd](https://github.com/slskd/slskd)

The script requires an api key from Slskd. Take a look at their [docs](https://github.com/slskd/slskd/blob/master/docs/config.md#authentication) on how to set it up (all you have to do is add it to the yml file under `web, authentication, api_keys, my_api_key`).

### Configure your config file:

The config file has a bunch of different settings that affect how the script runs. Any lists in the config such as "accepted_countries" need to be comma separated with no spaces (e.g. `","` not `" , "` or `" ,"`).

**Example config:**

```ini
[Lidarr]
api_key = yourlidarrapikeygoeshere
host_url = http://localhost:8686

[Slskd]
#Api key from Slskd. Need to set this up manually. See link to Slskd docs above.
api_key = yourslskdapikeygoeshere
host_url = http://localhost:5030
#Slskd download directory. Should have set it up when installing Slskd.
download_dir = /path/to/your/Slskd/downloads

[Release Settings]
#If true script will select the release with the most common amount of tracks out of all the releases.
use_most_common_tracknum = True
allow_multi_disc = True
#See full list of countries below.
accepted_countries = Europe,Japan,United Kingdom,United States,[Worldwide],Australia,Canada
#See full list of formats below.
accepted_formats = CD,Digital Media,Vinyl

[Search Settings]
search_timeout = 5000
maximum_peer_queue = 50
#Min upload speed in bit/s
minimum_peer_upload_speed = 0
#Replace "flac,mp3" with "flac" if you just want flacs.
allowed_filetypes = flac,mp3
ignored_users = User1,User2,Fred,Bob
```

[Full list of countries from Musicbrainz.](https://musicbrainz.org/doc/Release/Country)

[Full list of formats (also from Musicbrainz but for some reason they don't have a nice list)](https://pastebin.com/raw/pzGVUgaE)


I have included this [example config](https://github.com/mrusse/soularr/blob/main/config.ini) in the repo.

# Running The Script

You can simply run the script with:
```
python soularr.py
```
Note: the `config.ini` file needs to be in the same directory as `soularr.py`.

### Scheduling the script:

Scheduling the script is highly recommended since then all you have to do is add albums to the wanted list in Lidarr and the script will pick them up. I have included an [example bash script](https://github.com/mrusse/soularr/blob/main/run.sh) that can be scheduled using a [cron job](https://crontab.guru/every-5-minutes).

**Example cron job setup:**

Edit crontab file with 

```
crontab -e
```

Then enter in your schedule followed by the command. For example:

```
*/5 * * * * /path/to/run.sh
``` 

This would run the bash script every 5 minutes.

All of this is focused on Linux but the Python script runs fine on Windows as well. You can use things like the [Windows Task Scheduler](https://en.wikipedia.org/wiki/Windows_Task_Scheduler) to perform similar scheduling operations.

For my personal setup I am running the script on my Unraid server where both Lidarr and Slskd run as well. I run it using the [User Scripts](https://unraid.net/community/apps/c/plugins?q=User+scripts#r) plugin on a 5 minute schedule.

##
<p align="center">
  <a href='https://ko-fi.com/mrusse' target='_blank'><img height='35' style='border:0px;height:46px;' src='https://az743702.vo.msecnd.net/cdn/kofi3.png?v=0' border='0' alt='Buy Me a Coffee at ko-fi.com' /></a>
</p>
