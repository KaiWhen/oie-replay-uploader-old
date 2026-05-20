import schedule
import time
import os
import sys
from datetime import datetime, timedelta
from get_scores import get_top_scores
from mongo import mongo_client, scores_col, status_col
from configure_upload import (
    render_replay,
    upload_replay,
    dl_send_replay
)

QUOTA = 10000

def main_job():
    make_videos_public()
    status = status_col.find_one({"country": "IE"})
    now = datetime.now()
    minus_eight_hrs = timedelta(hours=-8)
    now_pt = now + minus_eight_hrs
    day_now_pt = now_pt.day
    if day_now_pt != status['calendar_day']:
        status_col.update_one({
            'country': 'IE'
        },{
            '$set': {
                'calendar_day': day_now_pt,
                'units_used': 0
            }
        }, upsert=False)

    render_not_sent = scores_col.find({"render_sent": False, "rendered": False})
    if render_not_sent:
        for score in render_not_sent:
            dl_send_replay(score['score_id'])

    not_rendered = scores_col.find({"render_sent": True, "rendered": False})
    if not_rendered:
        for score in not_rendered:
            score_id = score['score_id']
            render_replay(score_id)

    not_uploaded = scores_col.find({"rendered": True, "uploaded": False})
    if not_uploaded:
        for score in not_uploaded:
            score_id = score['score_id']
            status = status_col.find_one({"country": "IE"})
            if status["units_used"] + 1650 > QUOTA:
                continue
            if not upload_replay(score_id):
                sys.stdout.write("Upload not successful")

    score_ids = get_top_scores()
    if len(score_ids) == 0:
        sys.stdout.write("no scores lol")
        return -1
    
    for score_id in score_ids:
        dl_send_replay(score_id)
    

def main():
    try:
        mongo_client.admin.command('ping')
        sys.stdout.write("Pinged your deployment. You successfully connected to MongoDB!")
    except Exception as e:
        sys.stdout.write(e)

    check_dirs()
    main_job()
    schedule.every(5).minutes.do(main_job)

    while 1:
        schedule.run_pending()
        time.sleep(1)


def check_dirs():
    if not os.path.exists("videos/"):
        os.mkdir("videos/")
    if not os.path.exists("maps/"):
        os.mkdir("maps/")
    if not os.path.exists("replays/"):
        os.mkdir("replays/")


if __name__ == "__main__":
    main()
