import difflib
import time
import os
import shutil
import sys
import slskd_api
from pyarr import LidarrAPI

def album_match(lidarr_tracks, slskd_tracks):
    counted = []
    mp3 = False
    total_match = 0.0

    for lidarr_track in lidarr_tracks:
        lidarr_filename = lidarr_track['title'] + ".flac"
        best_match = 0.0

        for slskd_track in slskd_tracks:
            slskd_filename = slskd_track['filename']
            if(".mp3" in slskd_filename):
                mp3 = True
            ratio = difflib.SequenceMatcher(None, lidarr_filename, slskd_filename).ratio()

            if ratio > best_match:
                best_match = ratio

        if best_match > 0.5:
            counted.append(lidarr_filename)
            total_match += best_match

    print("\nNum matched: " + str(len(counted)) + " vs Total num: " + str(len(lidarr_tracks)))

    if(len(counted) == len(lidarr_tracks) and not mp3):
        print("Average sequence match ratio: " + str(total_match/len(counted)))
        print("SUCCESSFUL MATCH \n-------------------")
        return True
    
    print("FAILED MATCH \n-------------------")
    return False

def album_track_num(directory):
    files = directory['files']
    count = 0
    for file in files:
        if(".flac" in file['filename']):
            count += 1
    return count

def cancel_and_delete(delete_dir, directory):
    for bad_file in directory['files']:
        downloads = slskd.transfers.get_all_downloads()

        for user in downloads:
            for dir in user['directories']:
                for file in dir['files']:
                    if bad_file['filename'] == file['filename']:
                        slskd.transfers.cancel_download(username = user['username'], id = file['id'], remove= True)
                        time.sleep(.2)

    os.chdir(slskd_download_dir)
    shutil.rmtree(delete_dir)

def choose_release(album_id, artist_name):
    releases = lidarr.get_album(album_id)['releases']

    accepted_country = ["Europe","Japan","United Kingdom","United States","[Worldwide]","Australia","Canada"]
    accepted_formats = ["CD", "Digital Media"]

    for release in releases:
        country = release['country'][0] if release['country'] else None

        if (country in accepted_country 
            and release['format'] in accepted_formats
            and release['mediumCount'] == 1
            and release['status'] == "Official"):

            print("Selected release for " 
                  + artist_name + ": " 
                  + release['status'] + ", " 
                  + country + ", " 
                  + release['format'] 
                  + ", Mediums: " + str(release['mediumCount']))
            
            return release['id']
    
    return ""

def grab_most_wanted(albums):
    grab_list = []
    failed_download = 0

    for album in albums:
        artist_name = album['artist']['artistName']
        artist_id = album['artistId']
        album_id = album['id']

        release_id = choose_release(album_id, artist_name)

        if release_id != "":
            tracks = lidarr.get_tracks(artistId = artist_id, albumId = album_id, albumReleaseId = release_id)
        else:
            tracks = lidarr.get_tracks(artistId = artist_id, albumId = album_id)

        track_num = len(tracks)

        failed = True

        for track in tracks:
            querry = artist_name + " " + track['title']
            print("Search querry: " + querry)
            search = slskd.searches.search_text(searchText = querry, searchTimeout = 5000, filterResponses=True, maximumPeerQueueLength = 100)

            while True:
                if slskd.searches.state(search['id'])['state'] != 'InProgress':
                    break
                time.sleep(1)

            print("Search returned " + str(len(slskd.searches.search_responses(search['id']))) + " results")

            for result in slskd.searches.search_responses(search['id']):
                username = result['username']
                print("Parsing result from user: " + username)
                files = result['files']

                for file in files:
                    if('.flac' in file['filename']):
                        file_dir = file['filename'].rsplit("\\",1)[0]

                        try:
                            directory = slskd.users.directory(username = username, directory = file_dir)
                        except:
                            continue

                        if album_track_num(directory) == track_num:
                            if album_match(tracks, directory['files']):
                                for i in range(0,len(directory['files'])):
                                    directory['files'][i]['filename'] = file_dir + "\\" + directory['files'][i]['filename']
                                grab_list.append(artist_name + "|" + file_dir.split("\\")[-1])

                                try:
                                    slskd.transfers.enqueue(username = username, files = directory['files'])
                                except:
                                    cancel_and_delete(file_dir.split("\\")[-1], directory)
                                    continue
                                failed = False
                                break
                else:
                    continue
                break
            else:
                continue
            break

        if failed:
            print("ERROR: Failed to grab albumID: " + str(album_id) + " for artist: " + artist_name)
            failed_download += 1
            
    print("Downloads added: ")
    downloads = slskd.transfers.get_all_downloads()

    for download in downloads:
        username = download['username']
        for dir in download['directories']:
            print("Username: " + username + " Directory: " + dir['directory'])

    print("-------------------")
    print("Waiting for downloads... monitor at: " + slskd_host_url + "/downloads")

    while True:
        downloads = slskd.transfers.get_all_downloads()
        unfinished = 0
        for user in downloads:
            for directory in user['directories']:
                for file in directory['files']:
                    if file['state'] != 'Completed, Succeeded':
                        unfinished += 1
                    if file['state'] == 'Completed, Errored':
                        failed_download += 1
                        username = file['username']

                        delete_dir = directory['directory'].split("\\")[-1]
                        cancel_and_delete(delete_dir, directory)

        if(unfinished == 0):
            print("All tracks finished downloading!")
            time.sleep(5)
            break
    
    os.chdir(slskd_download_dir)
    commands = []
    grab_list.sort()

    for artist_folder in grab_list:
        artist_name = artist_folder.split("|")[0]
        folder = artist_folder.split("|")[1]

        shutil.move(folder,artist_name)

    artist_folders = next(os.walk('.'))[1]

    for artist_folder in artist_folders:
        command = lidarr.post_command(name = 'DownloadedAlbumsScan', path = '/data/' + artist_folder)
        commands.append(command)
        print("Starting Lidarr import for: " + artist_folder + " ID: " + str(command['id']))

    while True:
        completed_count = 0
        for task in commands:
            current_task = lidarr.get_command(task['id'])
            if current_task['status'] == 'completed':
                completed_count += 1
        if completed_count == len(commands):
            break

    for task in commands:
        current_task = lidarr.get_command(task['id'])
        try:
            print(current_task['commandName'] + " " + current_task['message'] + " from: " + current_task['body']['path'])
        except:
            print("Error printing lidarr task message. Printing full task.")
            print(current_task)
            
    return failed_download

with open('slskd.auth', 'r') as file:
    slskd_api_key = file.read().replace('\n', '')

with open('lidarr.auth', 'r') as file:
    lidarr_api_key = file.read().replace('\n', '')

slskd_download_dir = sys.argv[1]

lidarr_host_url = 'http://192.168.2.190:8686'
slskd_host_url = 'http://192.168.2.190:5030'

slskd = slskd_api.SlskdClient(slskd_host_url, slskd_api_key, '/')
lidarr = LidarrAPI(lidarr_host_url, lidarr_api_key)

for i in range(0,5):
    wanted = lidarr.get_wanted(sort_dir='ascending',sort_key='albums.title')['records']
    if len(wanted) > 0:
        try:
            failed = grab_most_wanted(wanted)
        except Exception as e: 
            print(e)
            print("\n Fatal error! Deleting all partial downloads and restarting.")

            downloads = slskd.transfers.get_all_downloads()

            for user in downloads:
                for dir in user['directories']:
                    for file in dir['files']:
                        slskd.transfers.cancel_download(username = user['username'], id = file['id'], remove= True)
                        time.sleep(.2)
            
            for item in os.listdir(slskd_download_dir):
                item_path = os.path.join(slskd_download_dir, item)
                if os.path.isfile(item_path):
                    os.remove(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            
            continue
        if failed == 0:
            print("Solarr finished. Exiting...")
            break
        else:
            print(failed + ": releases failed while downloading. Retying in 10 seconds...")
    else:
        print("No releases wanted. Exiting...")
        break
    
    time.sleep(10)