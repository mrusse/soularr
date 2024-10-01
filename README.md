# Soularr
Python script that connects Lidarr with Soulseek using the pyarr and slskd-api libraries. 
When ran the script will download anything from your "wanted" list in Lidarr using Slskd. View the demo below!

![Soularr_small](https://github.com/user-attachments/assets/15c47a82-ddf2-40e3-b143-2ad7f570730f)

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

The config file has a bunch of different settings that affect how the script runs. Any lists in the config such as "accepted_countries" need to be comma seperated with no spaces (e.g. `","` not `" , "` or `" ,"`).

**Example config:**

```ini
[Lidarr]
api_key = yourlidarrapikeygoeshere
host_url = http://localhost:8686

[Slskd]
#Api key from Slskd. Need to set this up manually. See link above.
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
minimum_peer_upload_speed = 0
#Replace "flac,mp3" with "flac" if you just want flacs.
allowed_filetypes = flac,mp3
ignored_users = User1,User2,Fred,Bob
```

[Full list of countries from Musicbrainz.](https://musicbrainz.org/doc/Release/Country)

[Full list of formats (also from Musicbrainz but for some reason they dont have a nice list)](https://pastebin.com/raw/pzGVUgaE)



I have included this [example config](https://github.com/mrusse/soularr/blob/main/config.ini) in the repo.
