#!/usr/bin/python

import httplib2
import os
import random
import time
import sys

from apiclient.discovery import build
from apiclient.errors import HttpError
from apiclient.http import MediaFileUpload
from google-auth.client import flow_from_clientsecrets
from google-auth.file import Storage
from google-auth.tools import run_flow, argparser

from mongo import scores_col, status_col, bot_col


# Explicitly tell the underlying HTTP transport library not to retry, since
# we are handling retry logic ourselves.
httplib2.RETRIES = 1

# Maximum number of times to retry before giving up.
MAX_RETRIES = 10

# Always retry when these exceptions are raised.
RETRIABLE_EXCEPTIONS = (httplib2.HttpLib2Error, IOError)

# Always retry when an apiclient.errors.HttpError with one of these status
# codes is raised.
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

# The CLIENT_SECRETS_FILE variable specifies the name of a file that contains
# the OAuth 2.0 information for this application, including its client_id and
# client_secret. You can acquire an OAuth 2.0 client ID and client secret from
# the Google API Console at
# https://console.cloud.google.com/.
# Please ensure that you have enabled the YouTube Data API for your project.
# For more information about using OAuth2 to access the YouTube Data API, see:
#   https://developers.google.com/youtube/v3/guides/authentication
# For more information about the client_secrets.json file format, see:
#   https://developers.google.com/api-client-library/python/guide/aaa_client_secrets
CLIENT_SECRETS_FILE = "tokens/client_secrets.json"

# This OAuth 2.0 access scope allows an application to upload files to the
# authenticated user's YouTube channel, but doesn't allow other types of access.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

# This variable defines a message to display if the CLIENT_SECRETS_FILE is
# missing.
MISSING_CLIENT_SECRETS_MESSAGE = """
WARNING: Please configure OAuth 2.0

To make this sample run you will need to populate the client_secrets.json file
found at:

   %s

with information from the API Console
https://console.cloud.google.com/

For more information about the client_secrets.json file format, please visit:
https://developers.google.com/api-client-library/python/guide/aaa_client_secrets
""" % os.path.abspath(os.path.join(os.path.dirname(__file__),
                                   CLIENT_SECRETS_FILE))

VALID_PRIVACY_STATUSES = ("unlisted", "private", "unlisted")


def get_authenticated_service():
    flow = flow_from_clientsecrets(CLIENT_SECRETS_FILE,
                                   SCOPES,
                                   message=MISSING_CLIENT_SECRETS_MESSAGE)

    storage = Storage("tokens/oauth2.json")
    credentials = storage.get()

    if credentials is None or credentials.invalid:
        # args = argparser.parse_args()
        # args.noauth_local_webserver = True
        credentials = run_flow(flow, storage)

    return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION,
                 http=credentials.authorize(httplib2.Http()))


youtube = get_authenticated_service()

def initialize_upload(options, score_id, thumb_path):
    tags = None
    if options['tags']:
        tags = options['tags'].split(",")

    body = dict(
        snippet=dict(
            title=options['title'],
            description=options['description'],
            tags=tags,
            categoryId=options['category']
        ),
        status=dict(
            privacyStatus=options['privacyStatus']
        )
    )

    # Call the API's videos.insert method to create and upload the video.
    insert_request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        # The chunksize parameter specifies the size of each chunk of data, in
        # bytes, that will be uploaded at a time. Set a higher value for
        # reliable connections as fewer chunks lead to faster uploads. Set a lower
        # value for better recovery on less reliable connections.
        #
        # Setting "chunksize" equal to -1 in the code below means that the entire
        # file will be uploaded in a single HTTP request. (If the upload fails,
        # it will still be retried where it left off.) This is usually a best
        # practice, but if you're using Python older than 2.6 or if you're
        # running on App Engine, you should set the chunksize to something like
        # 1024 * 1024 (1 megabyte).
        media_body=MediaFileUpload(options['file'], chunksize=-1, resumable=True)
    )
    sys.stdout.write(options['file'])
    resumable_upload(insert_request, score_id, thumb_path, options)

# This method implements an exponential backoff strategy to resume a
# failed upload.


def resumable_upload(insert_request, score_id, thumb_path, options):
    response = None
    error = None
    retry = 0
    while response is None:
        try:
            sys.stdout.write("Uploading file...")
            status_col.update_one({
                'country': 'IE'
            },{
                '$inc': {
                    'units_used': 1600
                }
            }, upsert=False)
            status, response = insert_request.next_chunk()
            if response is not None:
                if 'id' in response:
                    sys.stdout.write("Video id '%s' was successfully uploaded." %
                          response['id'])
                    
                    bot_col.update_one({
                        'country': 'IE'
                    },{
                        '$set': {
                            'new_upload_id': response['id']
                        }
                    }, upsert=False)

                    scores_col.update_one({
                        'score_id': score_id
                    },{
                        '$set': {
                            'uploaded': True,
                            'video_id': response['id']
                        }
                    }, upsert=False)

                    insert_req = youtube.thumbnails().set(
                        videoId=response['id'],
                        media_body=MediaFileUpload(thumb_path, chunksize=-1, resumable=True)
                    )
                    resumable_upload_thumbnail(insert_req)

                    os.remove(f"../{options['file']}")
                else:
                    exit("The upload failed with an unexpected response: %s" % response)
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES:
                error = "A retriable HTTP error %d occurred:\n%s" % (e.resp.status,
                                                                     e.content)
            else:
                raise
        except RETRIABLE_EXCEPTIONS as e:
            error = "A retriable error occurred: %s" % e

        if error is not None:
            sys.stdout.write(error)
            retry += 1
            if retry > MAX_RETRIES:
                exit("No longer attempting to retry.")

            max_sleep = 2 ** retry
            sleep_seconds = random.random() * max_sleep
            sys.stdout.write("Sleeping %f seconds and then retrying..." % sleep_seconds)
            time.sleep(sleep_seconds)


def resumable_upload_thumbnail(insert_request):
    response = None
    error = None
    retry = 0
    while response is None:
        try:
            sys.stdout.write("Uploading file...")
            status_col.update_one({
                'country': 'IE'
            },{
                '$inc': {
                    'units_used': 50
                }
            }, upsert=False)
            status, response = insert_request.next_chunk()
            if response is not None:
                sys.stdout.write("thumbnail was successfully uploaded.")
                # os.remove(options['file'])
            else:
                exit("The upload failed with an unexpected response: %s" % response)
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES:
                error = "A retriable HTTP error %d occurred:\n%s" % (e.resp.status,
                                                                     e.content)
            else:
                raise
        except RETRIABLE_EXCEPTIONS as e:
            error = "A retriable error occurred: %s" % e

        if error is not None:
            sys.stdout.write(error)
            retry += 1
            if retry > MAX_RETRIES:
                exit("No longer attempting to retry.")

            max_sleep = 2 ** retry
            sleep_seconds = random.random() * max_sleep
            sys.stdout.write("Sleeping %f seconds and then retrying..." % sleep_seconds)
            time.sleep(sleep_seconds)
