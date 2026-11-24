# Folder guide

[Русская версия](FOLDERS.ru.md)

The folders are in OBS: **Tools → Scripts → Moment Replays → Clip folders**.

## Choose where clips go

1. Look at the **Next clip** line. It shows where your next clip will be saved.
2. If that is fine, you are done. With no folder chosen, clips go to the OBS recording folder.
3. To change it, press **Browse** next to **Clips folder** and choose a folder **on the same drive
   as your OBS recordings**.
4. To go back, press **Use the OBS recording folder**.

Each game gets its own subfolder: `D:\Videos\Deadlock\`. Clips of apps from the *Other* list
(browsers, chats) go to `D:\Videos\Other\`. Missing folders are made when the first clip is saved.

Want clips on another drive? Change the recording path first, in OBS **Settings → Output**,
then choose a clips folder on that drive.

## More folders

Tick **More folders** to see these. You can leave them all alone.

| Folder | What it is for | Drive |
| --- | --- | --- |
| **Second clips folder** | Clips saved with the *Save buffer (override folder)* hotkey, without game subfolders. Empty: the clips folder. | Same as OBS recordings |
| **Recordings folder** | Full recordings started with the *Start/stop recording (alternative folder)* hotkey. Empty: the clips folder. | Any |
| **Shared folder** | Shows every clip from the clips folder a second time, all games together, without using more space. | Same as OBS recordings |
| **"Other" list** | Apps whose clips go to one `Other` subfolder instead of their own. | |

- The first two need **Extra hotkeys** to be on. Set the keys in OBS **Settings → Hotkeys**.
- The shared folder needs **Also collect all clips in one folder** to be on. Clips saved to the
  second clips folder do not appear there. To free the space of a clip, delete it in both places.
- Closing **More folders** only hides these settings. They keep working.

## Check that it works

1. Press **Check folders**. You should see "All folders checked: no problems."
2. Start the replay buffer, play for a minute and save a replay.
3. Open the folder from the **Next clip** line. The clip is in the game's subfolder.

## If you see a red line

| Message | What to do |
| --- | --- |
| **Not found** | The drive is not connected or has another letter. Connect it or choose another folder. |
| **Can't write** | Windows does not let OBS save there (for example `Program Files`). Choose another folder. |
| **Wrong drive** | Choose a folder on the drive named in the message, or change the recording path in OBS. |

While the clips folder has a red line, your clips are not lost: they stay in the OBS recording folder.
