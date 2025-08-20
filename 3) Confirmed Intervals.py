#!/usr/bin/env python3
"""
author: BL

After reconstructing 'Detection' events with applied speed & stationary filter, this script selects the uninterrupted detection periods which have at least one RFID match or RFID mismatch event in them.
- if a detection period has an RFID match, the entire detection period is considered
- if a detection period has an RFID mismatch in it, only the portion subsequent to the RFID mismatch (+ identity correction) is considered
- detection periods without RFID match or mismatch events are not considered

"""

import sqlite3
from lmtanalysis.FileUtil import getFilesToProcess
from lmtanalysis.Animal import AnimalPool
from lmtanalysis.Measure import oneDay
from lmtanalysis.Event import EventTimeLine
import os
import datetime

# Constants
frame_rate = 30
TMIN = 0
TMAX = 30 * oneDay
MATCH_MAX = 30 * oneDay
MISMATCH_MAX = 30 * oneDay
DETECTION_EVENT_NAME = "Detection"
MATCH_EVENT_NAME = "RFID MATCH"
MISMATCH_EVENT_NAME = "RFID MISMATCH"

#needs to match file name in downstream processing scripts
output_file = "confirmed_detection_intervals.txt"

def convert_timestamp(timestamp_ms):
    timestamp_s = timestamp_ms / 1000
    return datetime.datetime.fromtimestamp(timestamp_s, datetime.timezone.utc)

def convert_frames_to_time(total_frames, frame_rate):
    total_seconds = total_frames / frame_rate
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    return hours, minutes, seconds

def events_overlap(e1, e2):
    return not (e1.endFrame < e2.startFrame or e2.endFrame < e1.startFrame)

def get_mismatch_confirmed_interval(d_event, mismatchEvents):
    overlapping_mismatches = []
    for m_event in mismatchEvents:
        if events_overlap(d_event, m_event):
            overlapping_mismatches.append(m_event)

    if not overlapping_mismatches:
        return None

    max_end = max(m.endFrame for m in overlapping_mismatches)

    if max_end < d_event.endFrame:
        return (max_end+1, d_event.endFrame)
    else:
        return None

if __name__ == '__main__':
    files = getFilesToProcess()

    with open(output_file, 'w') as f:
        for file in files:
            sql_file_name = os.path.basename(file)
            connection = sqlite3.connect(file)
            f.write(f"Processing SQL file: {sql_file_name}\n")
            print(f"Processing SQL file: {sql_file_name}\n")

            cursor = connection.cursor()
            cursor.execute("SELECT TIMESTAMP FROM FRAME WHERE FRAMENUMBER = 1")
            start_timestamp_row = cursor.fetchone()
            start_timestamp = start_timestamp_row[0] if start_timestamp_row else None

            if start_timestamp:
                start_time = convert_timestamp(start_timestamp)
                f.write(f"Start Time of Experiment: {start_time}\n")
                print(f"Start Time of Experiment: {start_time}\n")
            else:
                f.write("No start timestamp found in FRAME table\n")
                print("No start timestamp found in FRAME table\n")

            query_max_frame = "SELECT MAX(FRAMENUMBER) FROM FRAME"
            cursor.execute(query_max_frame)
            max_frame = cursor.fetchone()[0]

            hours, minutes, seconds = convert_frames_to_time(max_frame, frame_rate)
            f.write(f"Max Frame: {max_frame}\n")
            f.write(f"Total Duration of Experiment: {hours}h {minutes}m {seconds}s ({max_frame} frames)\n")
            print(f"Max Frame: {max_frame}\n")
            print(f"Total Duration of Experiment: {hours}h {minutes}m {seconds}s ({max_frame} frames)\n")

            animalPool = AnimalPool()
            animalPool.loadAnimals(connection)
            animalPool.loadDetection(start=TMIN, end=TMAX)

            for animal_id, animal in animalPool.getAnimalDictionary().items():
                detectionTimeline = EventTimeLine(connection, DETECTION_EVENT_NAME, idA=animal_id, minFrame=TMIN, maxFrame=TMAX)
                matchTimeline = EventTimeLine(connection, MATCH_EVENT_NAME, idA=animal_id, minFrame=TMIN, maxFrame=MATCH_MAX)
                mismatchTimeline = EventTimeLine(connection, MISMATCH_EVENT_NAME, idA=animal_id, minFrame=TMIN, maxFrame=MISMATCH_MAX)

                total_detection_duration = sum(e.duration() for e in detectionTimeline.eventList)
                f.write(f"Animal {animal_id} (RFID: {animal.RFID}) - Detection total duration: {total_detection_duration} frames\n")

                confirmed_events = []
                sum_confirmed_duration = 0

                for d_event in detectionTimeline.eventList:
                    # RFID MATCH
                    match_found = False
                    for m_event in matchTimeline.eventList:
                        if events_overlap(d_event, m_event):
                            # => confirm entire detection period
                            startFrame, endFrame = d_event.startFrame, d_event.endFrame
                            dur = endFrame - startFrame + 1
                            confirmed_events.append((startFrame, endFrame, dur, "MATCH"))
                            sum_confirmed_duration += dur
                            match_found = True
                            break

                    if match_found:
                        continue

                    # MISMATCH => determine portion of detection period after MISMATCH
                    mismatch_interval = get_mismatch_confirmed_interval(d_event, mismatchTimeline.eventList)
                    if mismatch_interval is not None:
                        c_start, c_end = mismatch_interval
                        dur = c_end - c_start + 1
                        confirmed_events.append((c_start, c_end, dur, "MISMATCH"))
                        sum_confirmed_duration += dur

                if confirmed_events:
                    f.write("Confirmed Detection Intervals:\n")
                    print("Confirmed Detection Intervals:")
                    for startFrame, endFrame, dur, source in confirmed_events:
                        f.write(f"{startFrame} {endFrame} duration: {dur} (Confirmed by: {source})\n")
                        print(f"{startFrame} {endFrame} duration: {dur} (Confirmed by: {source})")

                    f.write(f"Total confirmed detection duration for animal {animal_id}: {sum_confirmed_duration} frames\n")
                    print(f"Total confirmed detection duration for animal {animal_id}: {sum_confirmed_duration} frames")
                else:
                    f.write("No confirmed detection events found.\n")
                    print("No confirmed detection events found.")

                f.write("=" * 50 + "\n")
                print("=" * 50)

            cursor.close()
            connection.close()

        f.write("All files processed.\n")
        print("All files processed.")
