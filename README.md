# Darksky Camera Operation

The Dusty Star Observatory webcam in St. Mary uploads photos every minute and a video timelapse once a day to the glacier.org FTP server.

## Photos

Twice a minute, this program grabs the image in the FTP folder, adds the GNPC logo, covers the ugly timestamp, adds a nicer looking timestamp, and uploads the new photo to the HTML server.

## Video

Once a day the timelapse video is grabbed and a logo is added to it, then it is uploaded to the HTML server and deleted from FTP. Video is deleted because it only changes once a day and we don't want to keep uploading it. Photos are not deleted from FTP because within a minute they will be overwritten anyways.

## Operation

Clone the repo into the device that will run it.

Add your environment file with the required passwords.

Run with cron every minute like: '\* \* \* \* \* cd ~/Modules/darksky-cam && ./main.py'
