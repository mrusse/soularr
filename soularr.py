from pyarr import LidarrAPI

host_url = 'http://192.168.2.190:8686'
api_key = '55ece427daa746568039b827b68e69fc'

lidarr = LidarrAPI(host_url, api_key)

for i in range (0,len(lidarr.get_wanted()['records'])):
    print(lidarr.get_wanted()['records'][i]['title'] + " - " + lidarr.get_wanted()['records'][i]['artist']['artistName'])