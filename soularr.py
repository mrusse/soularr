import asyncio
from typing import List
from pyarr import LidarrAPI
from aioslsk.transfer.model import Transfer
from aioslsk.client import SoulSeekClient
from aioslsk.search.model import SearchRequest
from aioslsk.events import SearchResult
from aioslsk.settings import Settings, CredentialsSettings

async def main():
    host_url = 'http://192.168.2.190:8686'
    api_key = '55ece427daa746568039b827b68e69fc'

    lidarr = LidarrAPI(host_url, api_key)

    #for i in range (0,len(lidarr.get_wanted()['records'])):
        #print(lidarr.get_wanted()['records'][i]['title'] + " - " + lidarr.get_wanted()['records'][i]['artist']['artistName'])

    settings: Settings = Settings(
        credentials=CredentialsSettings(
            username='M3H9Z',
            password='dagfa213241h'
        )
    )

    async with SoulSeekClient(settings) as client:
        await client.login()
        search_request: SearchRequest = await client.searches.search('Boombastic.flac')
        # Wait for a bit and get the first search result
        await asyncio.sleep(5)
        search_result: SearchResult = search_request.results[0]
        # The following will attempt to start the download in the background
        transfer: Transfer = await client.transfers.download(search_result.username, search_result.shared_items[0].filename)
        

        downloads: List[Transfer] = client.transfers.get_downloads()

        print(downloads)
        await asyncio.sleep(50)
asyncio.run(main())



