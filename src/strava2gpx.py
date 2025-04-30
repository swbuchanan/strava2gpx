import aiohttp
import aiofiles
import asyncio
import os
import logging

logger = logging.getLogger(__name__)

# (Elsewhere in your application setup, configure logging handlers/formatters,
# e.g. logging.basicConfig(level=logging.INFO) or more advanced config.)


class Strava2GPXError(Exception):
    """Base exception for errors in Strava2GPX operations"""
    pass # TODO: figure out what to do here

class Strava2GPX:
    def __init__(self, client_id, client_secret, refresh_token):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.access_token = None
        self.activities_list = None
        # I guess it's better to reuse one session for all requests
        self.session = aiohttp.ClientSession()
        self.streams = {
                        "latlng": 1, 
                        "altitude": 1, 
                        "heartrate": 0, 
                        "cadence": 0, 
                        "watts": 0, 
                        "temp": 0}

    async def connect (self):
        """Connect to Strava API and get the access token"""
        self.access_token = await self.refresh_access_token()

    # Gets a list of activities from Strava and stores them in self.activities_list
    # self.activities_list is a list of lists, where each inner list contains the activity name, activity ID, start date, and activity type
    # [activity_name, activity_id, start_date, activity_type] ex: ['Morning Run', 1234567890, '2021-01-01T00:00:00Z', 'Run']
    async def get_activities_list(self):
            activities = await self.get_strava_activities(1)
            masterlist = [[activity['name'], activity['id'], activity['start_date'], activity['type']] for activity in activities]
            print("Received " + str(len(masterlist)) + " activities")
            page = 1
            while len(activities) != 0:
                page += 1
                activities = await self.get_strava_activities(page)
                masterlist.extend([[activity['name'], activity['id'], activity['start_date'], activity['type']] for activity in activities])
                print("Received " + str(len(masterlist)) + " activities")
            self.activities_list = masterlist
            return masterlist
    
    async def refresh_access_token(self) -> str:
        """Fetch a new access token via OAuth refresh"""
        token_endpoint = 'https://www.strava.com/api/v3/oauth/token'

        form_data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token
        }

        try:
            logger.debug("Requesting new access token from Strava")
            resp = await self.session.post(token_endpoint, data=form_data)
            resp.raise_for_status()
        except aiohttp.ClientError as e:
            logger.error("HTTP error during token refresh %s", e, exc_info=True)
            raise Strava2GPXError("Failed to refresh access token") from e
        
        data = await resp.json()
        token = data.get("access_token")
        if not token:
            logger.error("No access_token in response payload %r", data)
            raise Strava2GPXError("Strava response missing access_token")
        
        logger.info("Successfully refreshed access token")
        self.access_token = token
        return token

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(token_endpoint, data=form_data) as response:
                    if response.status != 200:
                        if response.status == 401:
                            raise Exception('401 Unauthorized: Check Client ID, Client Secret, and Refresh Token')
                        else:
                            raise Exception('Failed to refresh access token')
                    data = await response.json()
                    self.access_token = data['access_token']
                    return self.access_token
            except Exception as e:
                print('Error refreshing access token:', str(e))
                raise

    async def get_strava_activities(self, page: int=1, per_page: int=200):
        """Fetch a page of activities."""
        if not self.access_token:
            await self.refresh_access_token()

        headers = {"Authorization": f"Bearer {self.access_token}"}
        params = {"page": page, "per_page": per_page}
        url = "https://www.strava.com/api/v3/athlete/activities"

        try:
            logger.debug("Fetching activities page=%d per_page=%d", page, per_page)
            resp = await self.session.get(url, headers=headers, params=params)
            resp.raise_for_status()
        except aiohttp.ClientResponseError as e:
            logger.error(
                "Strava API returned %d for activities: %s", e.status, e.message, exc_info=True
            )
            raise Strava2GPXError(f"Failed to fetch activities (status {e.status})") from e
        except aiohttp.ClientError as e:
            logger.error("Network error fetching activities: %s", e, exc_info=True)
            raise Strava2GPXError("Network error when fetching activities") from e

        activities = await resp.json()
        logger.info("Retrieved %d activities on page %d", len(activities), page)
        return activities

    async def get_data_stream(self, activity_id):
        """Get the data stream from one activity"""

        api_url = f'https://www.strava.com/api/v3/activities/{activity_id}/streams'
        query_params = 'time'
        headers = {
            'Authorization': f"Bearer {self.access_token}"
        }

        # check to see which streams we should be getting
        for key, value in self.streams.items():
            if value == 1:
                query_params += f',{key}'
        url = f'{api_url}?keys={query_params}&key_by_type=true'

        try:
            logger.debug("GET %s → headers=%r", url, headers)
            async with self.session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.json()
                logger.info(
                    "Retrieved %d streams for activity %d",
                    len(data), activity_id
                )
                return data

        except aiohttp.ClientResponseError as e:
            logger.error(
                "Strava API error %s for activity %d streams: %s",
                e.status, activity_id, e.message, exc_info=True
            )
            raise Strava2GPXError(
                f"Failed to fetch data streams for activity {activity_id} (HTTP {e.status})"
            ) from e

        except aiohttp.ClientError as e:
            logger.error(
                "Network error fetching streams for activity %d: %s",
                activity_id, e, exc_info=True
            )
            raise Strava2GPXError(
                f"Network error when fetching data streams for activity {activity_id}"
            ) from e

        # try:
        #     async with aiohttp.ClientSession() as session:
        #         async with session.get(url, headers={
        #             'Authorization': f'Bearer {self.access_token}'
        #         }) as response:
        #             if response.status != 200:
        #                 raise Exception(f'Failed to get data stream for activity {activity_id}')

        #             data = await response.json()
        #             return data
        # except Exception as e:
        #     print(f'Error getting data streams: {e}')
        #     raise

    async def get_strava_activity(self, activity_id):
        api_url = 'https://www.strava.com/api/v3/activities/'
        url = f'{api_url}{activity_id}?include_all_efforts=false'
        headers = {
            'Authorization': f"Bearer {self.access_token}"
        }

        try:
            logger.debug("GET %s -> headers=%r", url, headers)
            async with self.session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.json()
                logger.info(
                    "Retrieved data for activity %d",
                    activity_id
                )
                return data
            
        except aiohttp.ClientResponseError as e:
            logger.error(
                "Strava API error %d when fetching activity %d: %s", 
                e.status, activity_id, e.message, exc_info=True
            )
            raise Strava2GPXError(
                f"Failed to fetch data for activity {activity_id} (HTTP {e.status})"
            ) from e

        except aiohttp.ClientError as e:
            logger.error(
                "Network error when fetching data for activity %d: %s", 
                activity_id, e, exc_info=True
            )
            raise Strava2GPXError(
                f"Network error fetching data for activity {activity_id}"
            ) from e

        # try:
        #     async with aiohttp.ClientSession() as session:
        #         async with session.get(url, headers={
        #             'Authorization': f'Bearer {self.access_token}'
        #         }) as response:
        #             if response.status != 200:
        #                 raise Exception('Failed to get activity: response status 200.')

        #             data = await response.json()
        #             return data
        # except Exception as e:
        #     print(f'Error getting activity: {e}')
        #     raise

    async def detect_activity_streams(self, activity):
        if activity.get('device_watts', False):
            self.streams['watts'] = 1
        else:
            self.streams['watts'] = 0
        if activity['has_heartrate'] == True:
            self.streams['heartrate'] = 1
        else:
            self.streams['heartrate'] = 0
        if 'average_cadence' in activity:
            self.streams['cadence'] = 1
        else:
            self.streams['cadence'] = 0
        if 'average_temp' in activity:
            self.streams['temp'] = 1
        else:
            self.streams['temp'] = 0

    async def add_seconds_to_timestamp(self, start_timestamp, seconds):
        from datetime import datetime, timedelta
        start_time = datetime.fromisoformat(start_timestamp)
        new_time = start_time + timedelta(seconds=seconds)
        return (new_time.isoformat() + "Z").replace("+00:00", "")

    # Writes the activity to a GPX file called build.gpx
    async def write_to_gpx(self, activity_id, output="build"):
        activity = await self.get_strava_activity(activity_id)
        
        gpx_content_start = f'''<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd http://www.garmin.com/xmlschemas/GpxExtensions/v3 http://www.garmin.com/xmlschemas/GpxExtensionsv3.xsd http://www.garmin.com/xmlschemas/TrackPointExtension/v1 http://www.garmin.com/xmlschemas/TrackPointExtensionv1.xsd" creator="StravaGPX" version="1.1" xmlns="http://www.topografix.com/GPX/1/1" xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1" xmlns:gpxx="http://www.garmin.com/xmlschemas/GpxExtensions/v3">
 <metadata>
  <time>{activity['start_date']}</time>
 </metadata>
 <trk>
  <name>{activity['name']}</name>
  <type>{activity['type']}</type>
  <trkseg>'''
    
        gpx_content_end = '''
  </trkseg>
 </trk>
</gpx>
'''

        try:
            async with aiofiles.open(f"{output}.gpx", 'w') as f:
                await f.write(gpx_content_start)

            
            await self.detect_activity_streams(activity)
            data_streams = await self.get_data_stream(activity_id)

            if data_streams['latlng']['original_size'] != data_streams['time']['original_size']:
                print("Error: latlng does not equal Time")
                return

            trkpts = []
            for i in range(data_streams['time']['original_size']):
                time = await self.add_seconds_to_timestamp(activity['start_date'], data_streams['time']['data'][i])
                trkpt = f'''
   <trkpt lat="{float(data_streams['latlng']['data'][i][0]):.7f}" lon="{float(data_streams['latlng']['data'][i][1]):.7f}">
    <ele>{float(data_streams['altitude']['data'][i]):.1f}</ele>
    <time>{time}</time>
    <extensions>
     <gpxtpx:TrackPointExtension>
'''
                trkpts.append(trkpt)

                if self.streams['temp'] == 1:
                    trkpt = f'''      <gpxtpx:atemp>{data_streams['temp']['data'][i]}</gpxtpx:atemp>
'''
                    trkpts.append(trkpt)
                if self.streams['watts'] == 1:
                    trkpt = f'''      <gpxtpx:watts>{data_streams['watts']['data'][i]}</gpxtpx:watts>
'''
                    trkpts.append(trkpt)
                if self.streams['heartrate'] == 1:
                    trkpt = f'''      <gpxtpx:hr>{data_streams['heartrate']['data'][i]}</gpxtpx:hr>
''' 
                    trkpts.append(trkpt)

                if self.streams['cadence'] == 1:
                    trkpt = f'''      <gpxtpx:cad>{data_streams['cadence']['data'][i]}</gpxtpx:cad>
'''
                    trkpts.append(trkpt)

                trkpt =f'''     </gpxtpx:TrackPointExtension>
    </extensions>
   </trkpt>'''
                trkpts.append(trkpt)

            async with aiofiles.open(f"{output}.gpx", 'a') as f:
                await f.write(''.join(trkpts))
                await f.write(gpx_content_end)

            print(f'GPX file {output}.gpx saved successfully.')
        except Exception as err:
            print(f'Error writing GPX file: {err}')
