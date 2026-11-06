MINTRO website: deploying to your own domain on a Google Cloud VM
=================================================================

This package is the whole website plus install.sh, which sets up the nginx web server, points the site at
your domain, and turns on free HTTPS (Let's Encrypt). It suits a Google Cloud e2-micro VM running Debian or
Ubuntu. Replace your-domain.com and you@example.com below with your own.


1. Prepare the VM (Google Cloud console, once)
----------------------------------------------
- VPC network > IP addresses: reserve the VM's external IP as STATIC, so it never changes.
- Compute Engine > VM instances > your VM > Edit > Firewalls: tick "Allow HTTP traffic" and
  "Allow HTTPS traffic", then Save.


2. Point your domain at the VM (at your domain registrar, once)
---------------------------------------------------------------
- A record:  @    ->  the VM's external IP
- A record:  www  ->  the same IP          (or a CNAME: www -> your-domain.com)
Wait until it shows up (often minutes, sometimes an hour). Check with:  nslookup your-domain.com


3. Upload this zip to the VM
----------------------------
Easiest: open the VM's SSH window from the console, click "UPLOAD FILE" (top right) and choose the zip.
Or from your PC:
    gcloud compute scp mintro-website-*.zip YOUR-VM-NAME:~ --zone YOUR-ZONE
    (or: scp -i YOUR-KEY mintro-website-*.zip YOUR-USER@VM-IP:~)


4. Install (in the VM's SSH window)
-----------------------------------
    sudo apt-get update && sudo apt-get install -y unzip
    unzip -o mintro-website-*.zip
    cd mintro-website
    sudo bash install.sh your-domain.com you@example.com

Then open https://your-domain.com/

The email is only for Let's Encrypt (certificate expiry notices). Leave it out to install without HTTPS;
run the command again with it later. If your domain doesn't point at the VM yet, the script says so and
keeps the site on http:// until you run it again. Certificates renew by themselves.


5. Updating the site later
--------------------------
Upload the newer zip, then:
    unzip -o mintro-website-*.zip && cd mintro-website && sudo bash install.sh your-domain.com you@example.com
Only the site's files are replaced, all at once; web server settings and the certificate are kept.


What goes where
---------------
    /var/www/mintro                       the website
    /etc/nginx/sites-available/mintro     web server settings (certbot adds the HTTPS lines)
    /var/log/nginx/                       access and error logs


If something's wrong
--------------------
    sudo nginx -t                         checks the web server settings
    sudo systemctl status nginx           is the web server running?
    sudo tail -n 50 /var/log/nginx/error.log
    sudo certbot renew --dry-run          tests certificate renewal
    curl -I http://your-domain.com        does the VM answer at all? (no answer: check step 1's firewall)


Notes
-----
- The Download buttons point to the GitHub release (github.com/aiteleresearch/mintro/releases/latest),
  so the installer downloads come from GitHub, and GitHub counts them for the site's download counter.
- The live miner counter and the listing form need the stats service (docs/STATS.md in the repository);
  until then the site shows a dash for those numbers.
