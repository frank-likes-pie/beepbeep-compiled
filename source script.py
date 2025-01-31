# Licensed under GNU General Public License v3
from asyncio.log import logger
import datetime
import json
import pathlib
import re
import textwrap
import threading
import logging
import time
import os
import ctypes
import pygame
import sys
from pathlib import Path
from os.path import isfile, join, dirname, abspath
from dataclasses import dataclass
import pystray  # For system tray icon
from PIL import Image  # For handling the icon image



# You can change the logging level here. If stuff breaks, change set this to True to get more output
___DEBUG = False
if ___DEBUG:
    logging.basicConfig(format='%(asctime)s @ %(lineno)d  %(message)s', level=logging.DEBUG)
else:
    logging.basicConfig(format='%(asctime)s  %(message)s', level=logging.INFO)

### CONFIG

# Function to load friendly UUIDs from an external JSON file
def load_friendly_uuids():
    # Determine the base path (whether running as script or executable)
    if getattr(sys, 'frozen', False):  # If the script is compiled to an executable
        base_path = os.path.dirname(sys.executable)  # Path to the folder where the .exe is located
    else:
        base_path = os.path.dirname(__file__)  # Path to the script directory

    file_path = os.path.join(base_path, 'friendlies.json')
    
    try:
        with open(file_path, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"Error: The file at {file_path} was not found.")
        return {}
    except json.JSONDecodeError:
        print("Error: Failed to decode JSON from the file.")
        return {}

# Example usage
FRIENDLY_UUIDS = load_friendly_uuids()

# Printing the loaded friendly UUIDs
print(FRIENDLY_UUIDS)

BEEP_COOLDOWN_SECONDS = 5
###

@dataclass
class CommanderAndTimestamp:
    commander_id: int
    timestamp: datetime.datetime

class CommanderHistoryState:
    __listeners: list = []
    __last_cmdr_state: list[int] = []
    __most_recent_timestamp: datetime.datetime

    def subscribe_new_listener(self, cb):
        self.__listeners.append(cb)

    def get_init_debug_str(self, state: list[CommanderAndTimestamp]):
        output_lines = ["\t{}:{}\n".format(str(f.commander_id), str(f.timestamp)) for f in state]
        as_str = "".join(output_lines)
        return as_str

    def __init__(self, initial_state: list[CommanderAndTimestamp], name="None"):
        self.name = name
        logger.debug("Initializing new History State with the following initial state: \n%s", self.get_init_debug_str(initial_state))
        self._state = {}
        for entry in initial_state:
            self._state[entry.commander_id] = entry.timestamp
        self.__most_recent_timestamp = max(map(lambda x: x.timestamp, initial_state))

    def find_entry(self, commander_id) -> CommanderAndTimestamp | None:
        if commander_id in self._state.keys():
            return CommanderAndTimestamp(commander_id, self._state[commander_id])
        return None

    def _emit_events(self):
        data: list[CommanderAndTimestamp] = []
        keys = self._calculate_current_commander_ids()
        for key in keys:
            data.append(CommanderAndTimestamp(key, self._state[key]))
        for cb in self.__listeners:
            cb(data)

    def _calculate_current_commander_ids(self):
        return_commanders: list[int] = []
        for key in self._state:
            timestamp = self._state[key]
            if timestamp >= self.__most_recent_timestamp:
                return_commanders.append(key)
        return return_commanders

    def push_new_state(self, entries: list[CommanderAndTimestamp]):
        needs_emit = [self._update_entry(f) for f in entries]
        
        calculated_state = self._calculate_current_commander_ids()
        
        is_subset = True
        for entry in calculated_state:
            if entry not in self.__last_cmdr_state:
                is_subset = False
                break
        
        self.__last_cmdr_state.clear()
        for entry in calculated_state:
            self.__last_cmdr_state.append(entry)
        
        if any(needs_emit) and not is_subset:
            self._emit_events()

    def _update_entry(self, entry: CommanderAndTimestamp) -> bool:
        is_timestamp_newer = entry.timestamp > self.__most_recent_timestamp

        if is_timestamp_newer:
            logger.debug("New Most Recent Timestamp: %s", entry.timestamp)
            self.__most_recent_timestamp = entry.timestamp

        is_entry_new = entry.commander_id not in self._state.keys()
        self._state[entry.commander_id] = entry.timestamp
        
        return is_timestamp_newer or is_entry_new

    def get_most_recent_timestamp(self):
        return self.__most_recent_timestamp

class BeepHandler:
    def _beep(self):
        pygame.mixer.init()
        pygame.mixer.music.load(os.path.join(script_dir, "Bogey.wav"))  # Load the bogey sound relative to executable
        pygame.mixer.music.play()

    def _beep_friendly(self):
        pygame.mixer.init()
        pygame.mixer.music.load(os.path.join(script_dir, "Friendly.wav"))  # Load the friendly sound relative to executable
        pygame.mixer.music.play()


    def __init__(self, cooldown_seconds: int, friendly_ids: list[int], history_state_handles: list[CommanderHistoryState]) -> None:
        self.last_beep = datetime.datetime.now()
        self._cooldown = cooldown_seconds
        self._friendly = friendly_ids
        for entry in history_state_handles:
            entry.subscribe_new_listener(lambda x: self._handle_event(x, entry.name))
        
    def _handle_event(self, data : list[CommanderAndTimestamp], name: str = "None"):
        now = datetime.datetime.now()
        delta = (now - self.last_beep).total_seconds()
        if delta > self._cooldown:
            self.last_beep = now
            do_friendly_beep = all([f.commander_id in self._friendly for f in data])
            if do_friendly_beep:
                logger.info("History: %s A friend of yours is trying to steal your ganks :)", name)
                self._beep_friendly()
            else:
                logger.info("History: %s New CMDR in Instance", name)
                self._beep()

COMMANDER_HISTORY_DIR = join(os.getenv("LOCALAPPDATA"), "Frontier Developments", "Elite Dangerous", "CommanderHistory")
COMMANDER_HISTORY_LOOKUP: dict[int, CommanderHistoryState] = {}
LAST_MODIFIED_TIMESTAMP: datetime.datetime
CURRENT_VERSION: int = 1

def check_for_updates():
    try:
        import urllib.request
        resp = urllib.request.urlopen("https://raw.githubusercontent.com/CMDR-WDX/elite-beepbeep/master/version")
        version_online = int(resp.read().decode("utf-8"))
        download_url = "https://github.com/CMDR-WDX/elite-beepbeep"
        if version_online > CURRENT_VERSION:
            print(f"{'*' * 20}\n"
                  f"There is a new update available! Current local version is {CURRENT_VERSION}, available version is"
                  f" {version_online}.\nDownload at {download_url}\n{'*' * 20}")
        elif version_online == CURRENT_VERSION:
            print("This Version is Up to Date.")
    except Exception as err:
        print("Failed to check for an Update.")
        print(err)

def extract_commanders_from_history_file(abs_file_path: str) -> list[CommanderAndTimestamp]:
    def create_commander_entry(json_entry: dict) -> CommanderAndTimestamp:
        user_id = json_entry["CommanderID"]
        elite_epoch = json_entry["Epoch"]
        unix_epoch = convert_history_epoch_to_unix_epoch(elite_epoch)
        return CommanderAndTimestamp(user_id, datetime.datetime.fromtimestamp(float(unix_epoch)))

    with open(abs_file_path, "r") as file:
        try:
            data = json.load(file)
            all_in_list = [a for a in data["Interactions"]]
            return [create_commander_entry(a) for a in all_in_list if "Met" in a["Interactions"]]
        except Exception as err:
            logging.error("Failed to read json file. Skipping")
            logging.error(err)
            return []

def get_history_id_from_relative_filename(name: str) -> int:
    left_path = name.split(".")[0]
    just_number = left_path.removeprefix("Commander")
    return int(just_number)

def get_modified_files(first_run = False) -> list[str]:
    global LAST_MODIFIED_TIMESTAMP
    files_in_history_dir = [a for a in os.listdir(COMMANDER_HISTORY_DIR) if isfile(join(COMMANDER_HISTORY_DIR, a))]
    history_files = [a for a in files_in_history_dir if is_cmdr_history_file(a)]
    if first_run:
        history_file_to_cmdrs_in_list_lookup = \
            [(get_history_id_from_relative_filename(a),extract_commanders_from_history_file(join(COMMANDER_HISTORY_DIR, a))) for a in history_files]
        for history_file_id, entries in history_file_to_cmdrs_in_list_lookup:
            new_state = CommanderHistoryState(entries, str(history_file_id))
            global COMMANDER_HISTORY_LOOKUP
            COMMANDER_HISTORY_LOOKUP[history_file_id] = new_state

        LAST_MODIFIED_TIMESTAMP = datetime.datetime.now()

    new_history_files = [a for a in history_files if
                         check_if_file_is_newer_than_timestamp(join(COMMANDER_HISTORY_DIR, a), LAST_MODIFIED_TIMESTAMP)]
    LAST_MODIFIED_TIMESTAMP = datetime.datetime.now()
    return new_history_files

def check_if_file_is_newer_than_timestamp(filepath: str, timestamp: datetime.datetime) -> bool:
    as_path = pathlib.Path(filepath)
    last_modified = datetime.datetime.fromtimestamp(as_path.stat().st_mtime)
    return last_modified > timestamp

def is_cmdr_history_file(name: str) -> bool:
    regex = re.compile("^Commander\\d*\\.cmdrHistory$")
    temp = re.match(regex, name)
    return temp is not None

def convert_history_epoch_to_unix_epoch(history_epoch: int) -> int:
    return int((datetime.datetime(1601, 1, 1) + datetime.timedelta(seconds=history_epoch)).timestamp())

def print_commander_in_instance(c: int, friendly: bool):
    def get_friendly_name() -> str:
        keys = list(FRIENDLY_UUIDS.keys())
        vals = list(FRIENDLY_UUIDS.values())
        try:
            i = vals.index(c)
            return keys[i]
        except:
            return str(c)

    if friendly:
        cmdr_name = get_friendly_name()
        logging.info("CMDR {} came to steal your kills".format(cmdr_name))
    else:
        logging.info("CMDR w/ ID {} joined the instance".format(c))

def aggregate_most_recent_commanders(new_cmdr_files: list[str]) -> list[tuple[int, list[CommanderAndTimestamp]]]:
    return_entries: list[tuple[int, list[CommanderAndTimestamp]]] = []
    for entry in new_cmdr_files:
        history_id = get_history_id_from_relative_filename(entry)
        res = extract_commanders_from_history_file(join(COMMANDER_HISTORY_DIR, entry))
        history_file_timestamp = COMMANDER_HISTORY_LOOKUP[history_id].get_most_recent_timestamp()
        res_new = []
        for entry in res:
            delta = (entry.timestamp - history_file_timestamp).total_seconds()
            if delta > 0.0:
                res_new.append(entry)
        if len(res_new) > 0:
            return_entries.append((history_id, res_new))
    return return_entries

# Function to create the system tray icon
def create_tray_icon():
    # Check if the script is frozen (i.e., running as a bundled executable)
    if getattr(sys, 'frozen', False):
        # If the app is frozen, use _MEIPASS to access bundled resources
        icon_path = os.path.join(sys._MEIPASS, 'BeepBeep.ico')
    else:
        # If running as a script, use the script's directory
        icon_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'BeepBeep.ico')
    
    # Load the icon image
    icon_image = Image.open(icon_path)
    
    # Create the system tray icon
    icon = pystray.Icon("EliteBeepBeep", icon_image)
    
    # Add a left-click action to the icon
    icon.run(setup)

def setup(icon):
    icon.visible = True
    icon.menu = pystray.Menu(
        pystray.MenuItem('Test Bogey', test_bogey),  # Only the test sound option
        pystray.MenuItem('Test Friendly', test_friendly),  # Only the test sound option
        pystray.MenuItem('Show Window', show_window)  # New "Show Window" option
    )

def test_bogey(icon, item):
    # Play the bogey sound for the test
    beep_handler = BeepHandler(BEEP_COOLDOWN_SECONDS, FRIENDLY_UUIDS.values(), list(COMMANDER_HISTORY_LOOKUP.values()))
    beep_handler._beep()  # Play the bogey sound
    
    logging.info("Test Sound Triggered")
    
def test_friendly(icon, item):
    # Play the friendly sound for the test
    beep_handler = BeepHandler(BEEP_COOLDOWN_SECONDS, FRIENDLY_UUIDS.values(), list(COMMANDER_HISTORY_LOOKUP.values()))
    beep_handler._beep_friendly()  # Play the friendly sound
    
    logging.info("Test Sound Triggered")
    
def show_window(icon, item):
    # Use Windows API to bring the console window to the front
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 5)  # 5 = SW_SHOW
    ctypes.windll.user32.SetForegroundWindow(ctypes.windll.kernel32.GetConsoleWindow())  # Bring it to the front

    logging.info("Show window requested")

# Get the directory of the script
import os

# Get the directory where the executable is located
script_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))


check_for_updates()
# Initial Setup
get_modified_files(True)

# Set up a Beeper.
beeper = BeepHandler(BEEP_COOLDOWN_SECONDS, FRIENDLY_UUIDS.values(), list(COMMANDER_HISTORY_LOOKUP.values()))

logging.info("Ready and polling. %s History files are being polled.", (len(COMMANDER_HISTORY_LOOKUP.keys())))

# Start the tray icon
threading.Thread(target=create_tray_icon, daemon=True).start()

while True:
    time.sleep(1)
    logging.debug("\n\nStart new Poll")
    try:
        new_cmdr_history_files = get_modified_files()
        logger.debug("%d Logfiles modified.", len(new_cmdr_history_files))
        if len(new_cmdr_history_files) == 0:
            logging.debug("No newly modified Log file")
            continue
        most_recent_commanders = aggregate_most_recent_commanders(new_cmdr_history_files)
        if len(most_recent_commanders) == 0:
            logging.debug("Logfile modified, but no new CMDR entries")
            continue
        for history_file_id, update_state in most_recent_commanders:
            COMMANDER_HISTORY_LOOKUP[history_file_id].push_new_state(update_state)
    except Exception as err:
        logging.exception("Whoops. Something broke in the main loop.")
        raise err
