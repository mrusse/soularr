from pyarr import LidarrAPI
import slskd_api

with open('slskd.auth', 'r') as file:
    slskd_api_key = file.read().replace('\n', '')

with open('lidarr.auth', 'r') as file:
    lidarr_api_key = file.read().replace('\n', '')

host_url = 'http://192.168.2.190:8686'

lidarr = LidarrAPI(host_url, lidarr_api_key)
artistName = lidarr.get_wanted()['records'][0]['artist']['artistName']
artistID = lidarr.get_wanted()['records'][0]['artistId']
albumID = lidarr.get_wanted()['records'][0]['id']

tracks = lidarr.get_tracks(artistId = artistID, albumId = albumID)
test_querry = artistName + " " + tracks[0]['trackNumber'] + " " + tracks[0]['title'] + ".flac"

print(test_querry)

slskd = slskd_api.SlskdClient('http://192.168.2.190:5030', slskd_api_key, '/')
search = slskd.searches.search_text(test_querry)

while(True):
    if slskd.searches.state(search['id'])['state'] != 'InProgress':
        break

for result in slskd.searches.search_responses(search['id']):
   if(len(result['files']) == 1 and '.flac' in result['files'][0]['filename']):
        print(result['files'])
        break

slskd.transfers.enqueue(username=result['username'], files=result['files'])