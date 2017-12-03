import os


class Settings:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Admin IDs who has access to bot commands
    # admin_ids = [194764515, 273428117]
    admin_ids = []
    # Telegram autorisation token
    token = ''
    # Path to store torrent files
    # torrent_path = '/mnt/archive2/onedrive/.torrents/video/films/'
    torrent_path = ''

    # Couchpotato related settings:
    # Hostname
    cp_hostname = 'localhost'
    # API Key
    cp_api = ''
    # Port
    cp_port = '5050'
    # URL Base
    cp_urlbase = '/couchpotato'
    # SSL
    cp_ssl = False
    # Username
    cp_username = 'admin'
    # Password
    cp_password = 'admin'
    # Timeout
    cp_timeout = 15
