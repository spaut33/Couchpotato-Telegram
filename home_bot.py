#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import subprocess
import re
import platform
import pickle
from datetime import datetime, date, time
from functools import wraps
from telegram.ext import Updater, CommandHandler, MessageHandler
from telegram.ext import BaseFilter, Filters, CallbackQueryHandler
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import ChatAction, ParseMode, KeyboardButton
from settings import Settings


# Logging Configuration
logging.basicConfig(
    format=u'%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
logger = logging.getLogger(__name__)


# Restricted access decorator
# We are going to check user_id with allowed users from settings
def restricted(func):
    @wraps(func)
    def wrapped(bot, update, *args, **kwargs):
        try:
            user_id = update.message.from_user.id
        except (NameError, AttributeError):
            try:
                user_id = update.inline_query.from_user.id
            except (NameError, AttributeError):
                try:
                    user_id = update.chosen_inline_result.from_user.id
                except (NameError, AttributeError):
                    try:
                        user_id = update.callback_query.from_user.id
                    except (NameError, AttributeError):
                        logger.warn("No user_id available in update.")
                        return
        if user_id not in Settings.admin_ids:
            logger.warn(u"Доступ запрещен. UID: " + str(user_id))
            bot.sendMessage(chat_id=update.message.chat_id,
                            text=u"Доступ неавторизованным пользователям " +
                            "запрещен!\n" +
                            "https://www.youtube.com/watch?v=D1FWk_DP7rU")
            return
        return func(bot, update, *args, **kwargs)
    return wrapped


class CP:

    @restricted
    def avail(bot, update):
        result = CP.api_request('media.list', '?release_status=available&status=active')
        logger.info("Couchpotato получает список доступных к закачке фильмов")
        if result:
            bot.sendChatAction(chat_id=update.message.chat_id,
                               action=ChatAction.TYPING)
            for sublist in result['movies']:
                logger.info('Couchpotato нашла: "' + sublist['title'] + '" ID: ' + sublist['releases'][0]['media_id'])
                output = sublist['title'] + ' ' + \
                    str(sublist['info']['year']) + '\n'
                keyboard = [[InlineKeyboardButton("Скачать", callback_data='dow_' + sublist['identifiers']['imdb']),
                             InlineKeyboardButton("Удалить", callback_data='del_' + sublist['releases'][0]['media_id'])]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                # bot.sendPhoto(chat_id=update.message.chat_id, photo=open(sublist['files']['image_poster'][0], 'rb'))
                bot.sendMessage(chat_id=update.message.chat_id,
                                text=output, reply_markup=reply_markup)
            with open('cache/cp_avail_' +
                      str(update.message.chat_id), 'wb') as cache:
                pickle.dump(result['movies'], cache)
        else:
            logger.error(u"Не получена информация от media.list")

    @restricted
    def button(bot, update):
        q = update.callback_query
        action = q.data[:4]
        movie_id = q.data[4:]
        button_list = []
        output = ''
        max_entries = 5

        with open('cache/cp_avail_' + str(q.message.chat_id), 'rb') as cache:
            movies = pickle.load(cache)

        if (action == 'dow_'):
            if movies:
                logger.info(
                    'Пытаемся найти в кэше доступные релизы для фильма с ID: ' +
                    movie_id)
                for entry in movies:
                    if movie_id == entry['identifiers']['imdb']:
                        movie_title = entry['info']['titles'][0] + ' ' + \
                            str(entry['info']['year'])
                        logger.info('Фильм ' + movie_id +
                                    ' найден в кэше, получаем доступные релизы')
                        i = 1
                        output = output + '<b>' + movie_title + '</b>\n'
                        for release in entry['releases']:
                            output = output + \
                                '<b>' + str(i) + '. 💿' + \
                                release['info']['name'] + \
                                release['info']['protocol'] + '</b>\n' + \
                                str(release['info']['size']) + 'Mb | ' + \
                                '<a href="' + release['info']['url'] + '">' + \
                                release['info']['provider'] + '</a>' + \
                                ' |score: ' + \
                                str(release['info']['score']) + '|⇩' + \
                                str(release['info']['leechers']) + '|⇧' + \
                                str(release['info']['seeders']) + \
                                '\n'
                            button_list.append(InlineKeyboardButton(str(i), callback_data='add_' + release['_id']))
                            reply_markup = InlineKeyboardMarkup(build_menu(button_list, n_cols=max_entries))
                            logger.info('Найден релиз: ' + release['info']['name'])
                            if i >= max_entries:
                                break
                            else:
                                i = i + 1
            else:
                error = u"Нет доступа к закэшированным результатам cp_avail"
                logger.error(error)
                output = error
            bot.editMessageText(text=output,
                                chat_id=q.message.chat_id,
                                message_id=q.message.message_id,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup)
        elif (action == 'del_'):
            logger.info('Удаляем релиз: ' + movie_id)
            if (CP.api_request('movie.delete', '?id=' + movie_id)):
                logger.info('Релиз успешно удален')
                bot.editMessageText(text='Удалено',
                                chat_id=q.message.chat_id,
                                message_id=q.message.message_id)
            else:
                logger.error('Релиз не удален из CP: ' + movie_id)
        elif (action == 'add_'):
            logger.info('Добавляем принудительно на закачку релиз: ' + movie_id)
            if (CP.api_request('release.manual_download', '?id=' + movie_id)):
                logger.info('Успешно добавлен на закачку')
                bot.editMessageText(text='Релиз добавлен на закачку',
                                chat_id=q.message.chat_id,
                                message_id=q.message.message_id)
            else:
                logger.error('Релиз не добавлен на закачку: ' + movie_id)

    @restricted
    def query(bot, update):
        bot.sendChatAction(chat_id=update.message.chat_id,
                           action=ChatAction.TYPING)
        result = CP.api_request('search', '?q=' + update.message.text[3:])
        logger.info(
            u"Couchpotato получает список фильмов по запросу: " +
            update.message.text[3:])
        if 'movies' in result:
            button_list = []
            film_list = ''
            n = 1
            for entry in result['movies']:
                year = entry['year']
                imdb_rating = entry['rating']['imdb'][0]
                imdb_votes = entry['rating']['imdb'][1]
                href = '<a href="http://imdb.com/title/' + \
                    entry['imdb'] + '/">'
                film_list += str(n) + '. '
                film_list += href + entry['titles'][0] + '</a> '
                film_list += str(year) + ' '
                film_list += '<i>' + str(imdb_rating)
                film_list += '/' + str(imdb_votes) + '</i>\n'
                button_text = entry['titles'][0] + ' ' + str(year)
                button_list.append(KeyboardButton(text=button_text))
                n = n + 1
                logger.info(u"Couchpotato нашла кандидата: " +
                            entry['titles'][0] + " IMDB ID:" + entry['imdb'])
            with open('cache/cp_' +
                      str(update.message.chat_id), 'wb') as cache:
                pickle.dump(result['movies'], cache)
            output = u"<b>Найдены следующие фильмы:</b>" + '\n' + film_list
            reply_markup = ReplyKeyboardMarkup(build_menu(button_list,
                                                          n_cols=1
                                                          ))
            bot.sendMessage(chat_id=update.message.chat_id,
                            text=output, reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML)
        else:
            output = u"Ничего не нашлось. Попробуйте другой вариант названия."
            bot.sendMessage(chat_id=update.message.chat_id,
                            text=output)

    def api_request(action, query):
        import requests
        cp_url = 'http://{host}:{port}{dir}/api/{api}/{action}/{query}'.format(
            host=Settings.cp_hostname,
            port=Settings.cp_port,
            dir=Settings.cp_urlbase,
            api=Settings.cp_api,
            action=action,
            query=query)
        try:
            request = requests.get(cp_url, timeout=Settings.cp_timeout)
            # For test purposes only:
            # request = requests.get('http://pastebin.com/raw/FdRQb92H',
            # timeout=Settings.cp_timeout)
            if action == 'search' or action == 'media.list':
                return request.json()
            else:
                return request.json()['success']
        except requests.RequestException as error:
            logger.error(u'Ошибка подключения к CouchPotato: {}'.
                         format(error))
            return None


@restricted
def plain_text(bot, update):
    bot.sendChatAction(chat_id=update.message.chat_id,
                       action=ChatAction.TYPING)
    output = ""
    try:
        with open('cache/cp_' + str(update.message.chat_id), 'rb') as cache:
            movies = pickle.load(cache)
    except OSError:
        output = "Нет закэшированных результатов поиска"
        movies = ()
    if movies:
        movie_title = update.message.text[:-5]
        movie_year = int(update.message.text[-4:])
        for entry in movies:
            if movie_title in entry['titles'] and movie_year == entry['year']:
                logger.info("Фильм %s: %s найден, пробуем добавить в CouchPotato" %
                            (movie_title, str(movie_year)))
                output = add_movie(movie_title, entry['imdb'])

    # FIXME: output still can be None. "" also isn't good for send_message's text parameter.
    bot.send_message(chat_id=update.message.chat_id,
                     text=output if output else "None",
                     parse_mode=ParseMode.HTML,
                     reply_markup=ReplyKeyboardRemove())


def add_movie(movie_title, movie_id):
    media_list = CP.api_request('media.list', '')
    logger.info("Couchpotato проверяет, есть ли такой фильм уже в ее базе: " +
                movie_title + " IMDB ID:" + movie_id)
    if media_list:
        for sublist in media_list['movies']:
            if movie_id == sublist['identifiers']['imdb']:
                error = u"Couchpotato нашла этот фильм в своей базе. " + \
                        u"Задание на поиск не добавлено."
                logger.warn(error)
                return error
        else:
            if CP.api_request('movie.add', '?identifier=' +
                              movie_id + '&amp;title=' + movie_title):
                output = u"Фильм добавлен в очередь на закачку " + \
                         u"<a href=\"http://imdb.com/title/" + \
                         movie_id + "\">" + movie_title + \
                         "</a>\nCouchpotato попробует найти его и скачает," + \
                         " а по завершении пришлет сообщение."
            else:
                output = u"Ошибка при добавлении фильма в CP (movie.add)"
            logger.info(output)
            return output
    else:
        logger.error(u"Не получена информация от media.list")


# If we encounter updater's error we will log it
def error(bot, update, error):
    logger.warn('Update "%s" caused error "%s"' % (update, error))


# /start command
@restricted
def start(bot, update):
    bot.sendChatAction(chat_id=update.message.chat_id,
                       action=ChatAction.TYPING)
    bot.sendMessage(chat_id=update.message.chat_id,
                    text="Привет, я " + bot.username +
                    "! Набери /help для получения помощи")
    logger.info(u"Пользователь ID:" +
                str(update.message.chat_id) + " отправил команду /start")


# /help command
@restricted
def help(bot, update):
    help = """<b>/help</b> - Помощь
<b>/q название фильма</b> - Поиск фильма и добавление в очередь на скачивание
<b>/ping</b> - Пинг до гугла
<b>/uptime</b> - Аптайм сервера
<b>/free</b> - Свободная память
<b>/systemp</b> - Температура сервера

Бот также принимает ссылки на страницы, где есть magnet-ссылки,
а также сами magnet-ссылки и torrent-файлы
©2017, by @photopiter"""
    bot.sendChatAction(chat_id=update.message.chat_id,
                       action=ChatAction.TYPING)
    bot.sendMessage(chat_id=update.message.chat_id,
                    text=help, parse_mode=ParseMode.HTML)
    logger.info(u"Пользователь ID:" +
                str(update.message.chat_id) + " отправил команду /help")


# /ping command
# This command is win/*nix compatible
@restricted
def ping(bot, update):
    bot.sendChatAction(chat_id=update.message.chat_id,
                       action=ChatAction.TYPING)
    output = u"Пинг до гугла: " + str(do_ping("8.8.4.4", 2)) + u"мс."
    bot.sendMessage(chat_id=update.message.chat_id, text=output)
    logger.info(u"Пользователь ID:" +
                str(update.message.chat_id) + " отправил команду /ping")


# /uptime command
# This command is win/*nix compatible
# 'net stats srv' used @ windows systems
@restricted
def uptime(bot, update):
    bot.sendChatAction(chat_id=update.message.chat_id,
                       action=ChatAction.TYPING)
    if platform.system() == "Windows":
        uptime = subprocess.check_output('net stats srv', shell=True)
        matches = re.match('.*(\d{2}.\d{2}.\d{4}).*',
                           str(uptime), re.DOTALL)
        uptime = matches.group(1)
        start_date = datetime.date(datetime.strptime(uptime, '%d.%m.%Y'))
        current_date = date.today()
        uptime = str(current_date - start_date)
    else:
        uptime = subprocess.check_output('uptime -p', shell=True)
    bot.sendMessage(chat_id=update.message.chat_id,
                    text=u'Аптайм: ' + uptime.decode('utf-8'))
    logger.info(u"Пользователь ID:" + str(update.message.chat_id) +
                " отправил команду /uptime")


@restricted
def free(bot, update):
    bot.sendChatAction(chat_id=update.message.chat_id,
                       action=ChatAction.TYPING)
    if platform.system() == "Windows":
        # TODO: Format output
        mem = subprocess.check_output('wmic OS get FreePhysicalMemory /Value',
                                      shell=True)
        hdd = subprocess.check_output('wmic /node:"%COMPUTERNAME%" LogicalDisk Where DriveType="3" Get DeviceID,FreeSpace',
                                      shell=True)
    else:
        mem = subprocess.check_output(r'free -m | sed -n "s/^Mem:\s\+[0-9]\+\s\+\([0-9]\+\)\s.\+/\1/p"',
                                      shell=True).decode('utf-8')
        hdd = subprocess.check_output(r"df -h | sed -n 4p | awk '{ print $4 }'",
                                      shell=True).decode('utf-8')
    output = "Free RAM, Mb: " + str(mem) + "Free Disk: " + str(hdd)
    bot.sendMessage(chat_id=update.message.chat_id, text=output)
    logger.info(u"Пользователь ID:" +
                str(update.message.chat_id) + " отправил команду /free")


@restricted
def systemp(bot, update):
    bot.sendChatAction(chat_id=update.message.chat_id,
                       action=ChatAction.TYPING)
    if platform.system() == "Windows":
        output = u"Команда не доступна, потому что бот " + \
                 u"запущен на платформе " + platform.system()
    else:
        output = subprocess.check_output(r'sensors | sed -ne "s/ Temp: \+[-+]\([0-9]\+\).*/: \1°C/p"',
                                         shell=True).decode('utf-8')
    bot.sendMessage(chat_id=update.message.chat_id, text=output)
    logger.info(u"Пользователь ID:" + str(update.message.chat_id) +
                " отправил команду /systemp")


@restricted
def http_parse(bot, update, direct=True):
    import requests
    t = update.message.text
    matches = re.match('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
                       t, re.DOTALL)
    url = matches.group(0)
    logger.info(u"Пользователь ID:" + str(update.message.chat_id) +
                " отправил команду ссылку на страницу " + url)
    logger.info('Ищем magnet-ссылку по URL: ' + url)
    r = requests.get(url)
    magnet = re.search('href=[\'"]?(magnet[^\'" >]+)', r.text, re.DOTALL)
    if magnet.group(1):
        logger.info(u"Magnet-ссылка найдена на странице")
        output = magnet_save(magnet.group(1))
        if not output:
            output = u"Magnet-ссылка не сохранена, потому что " + \
                     u"бот запущен на платформе Windows"
            logger.warn(output)
        else:
            logger.info(u"Magnet-ссылка сохранена")
    else:
        output = u'Magnet-ссылка не найдена на странице по ссылке.'
        logger.warn(u"Magnet-ссылка не найдена на странице:" + url)
    bot.sendMessage(chat_id=update.message.chat_id, text=output)


@restricted
def magnet_parse(bot, update, direct=True):
    bot.sendChatAction(chat_id=update.message.chat_id,
                       action=ChatAction.TYPING)
    logger.info(u"Пользователь ID:" +
                str(update.message.chat_id) + " отправил Magnet-ссылку")
    output = magnet_save(update.message.text)
    bot.sendMessage(chat_id=update.message.chat_id, text=output)


@restricted
def torrent_save(bot, update, direct=True):
    bot.sendChatAction(chat_id=update.message.chat_id,
                       action=ChatAction.TYPING)
    logger.info(u"Пользователь ID:" +
                str(update.message.chat_id) + " отправил torrent-файл")
    f = update.message.document
    torrent_file = bot.getFile(f.file_id)
    if torrent_file.download(Settings.torrent_path + f.file_name):
        output = f.file_name + u' успешно загружен и передан на закачку.'
        logger.info(output)
    else:
        output = u'Ошибка при сохранении torrent-файла.'
        logger.warn(output)
    bot.sendMessage(chat_id=update.message.chat_id, text=output)


def magnet_save(magnet):
    if platform.system() == "Windows":
        return False
    import libtorrent
    timeout = 30
    params = libtorrent.parse_magnet_uri(magnet)
    session = libtorrent.session()
    handle = session.add_torrent(params)
    timeout_value = timeout

    while not handle.has_metadata():
        time.sleep(0.1)
        timeout_value -= 0.1
        if timeout_value <= 0:
            logger.error(u'Таймаут после %s секунд при получении \
                         данных торрента с DHT/трекеров.',
                         timeout)
            return u'Таймаут после {} секунд при получении \
                         данных торрента с DHT/трекеров.'.format(timeout)
        else:
            return u'Magnet-ссылка успешно передана на закачку'

    torrent_info = handle.get_torrent_info()
    torrent_file = libtorrent.create_torrent(torrent_info)
    with open(Settings.torrent_path + torrent_info.name() +
              ".torrent", "wb") as f:
        f.write(libtorrent.bencode(torrent_file.generate()))
    f.close()


def unknown(bot, update):
    bot.sendMessage(chat_id=update.message.chat_id,
                    text='Извините, я не понимаю этой команды. Помощь: /help')


# Build Menu Helper
def build_menu(buttons: list,
               n_cols: int,
               header_buttons: list = None,
               footer_buttons: list = None):
    menu = list()
    for i in range(0, len(buttons)):
        item = buttons[i]
        if i % n_cols == 0:
            menu.append([item])
        else:
            menu[int(i / n_cols)].append(item)
    if header_buttons:
        menu.insert(0, header_buttons)
    if header_buttons:
        menu.append(footer_buttons)
    return menu


# Internal function to do ping
def do_ping(hostname, timeout):
    if platform.system() == "Windows":
        command = "ping " + hostname + " -n 1 -w " + str(timeout * 1000)
        pattern = '.*xef=([0-9]+).*'
    else:
        command = "ping -i " + str(timeout) + " -c 1 " + hostname
        pattern = '.*time=([0-9]+\.[0-9]+) ms.*'
    proccess = subprocess.Popen(command, stdout=subprocess.PIPE, shell=True)
    matches = re.match(pattern,
                       str(proccess.stdout.read().decode('utf-8')), re.DOTALL)
    if matches:
        return matches.group(1)
    else:
        return False


def Filter(f):
    def filter_wrapper(self, message):
        return f(self, message)
    return type(f.__name__, (BaseFilter,), {'__call__': filter_wrapper})()


@Filter
def torrent_file(self, message):
    t = message.document
    return bool(t and t.mime_type == 'application/x-bittorrent')


@Filter
def magnet(self, message):
    return bool(message.text and message.text.startswith('magnet'))


@Filter
def http_link(self, message):
    return bool(message.text and message.text.startswith('http'))


# Start point. Here we go
def main():
    # Updater Initialization
    logger.info(u"Инициализация")
    u = Updater(token=Settings.token)
    logger.info(u"Апдейтер запущен")
    dp = u.dispatcher

    # Initialize handlers
    start_handler = CommandHandler('start', start)
    help_handler = CommandHandler('help', help)
    ping_handler = CommandHandler('ping', ping)
    uptime_handler = CommandHandler('uptime', uptime)
    free_handler = CommandHandler('free', free)
    systemp_handler = CommandHandler('systemp', systemp)
    cp_query_handler = CommandHandler('q', CP.query)
    cp_avail_handler = CommandHandler('avail', CP.avail)
    magnet_handler = MessageHandler(magnet, magnet_parse)
    http_handler = MessageHandler(http_link, http_parse)
    torrent_file_handler = MessageHandler(torrent_file, torrent_save)
    plaintext_handler = MessageHandler(Filters.text, plain_text)
    unknown_handler = MessageHandler(Filters.command, unknown)
    button_handler = CallbackQueryHandler(CP.button)

    logger.info(u"Инициализация диспатчеров")
    # Initialize dispatchers for commands
    dp.add_handler(start_handler)
    dp.add_handler(help_handler)
    dp.add_handler(ping_handler)
    dp.add_handler(uptime_handler)
    dp.add_handler(systemp_handler)
    dp.add_handler(free_handler)
    dp.add_handler(button_handler)

    # Dispatchers for text commands without /
    # This is http and magnet: links, also text for couchpotato finder
    dp.add_handler(magnet_handler)
    dp.add_handler(http_handler)
    dp.add_handler(torrent_file_handler)
    dp.add_handler(plaintext_handler)

    # Dispatchers for couchpotato
    dp.add_handler(cp_query_handler)
    dp.add_handler(cp_avail_handler)

    # Also for unknown command
    dp.add_handler(unknown_handler)

    # Log errors
    dp.add_error_handler(error)

    logger.info(u"Запуск очереди сообщений === Конец инициализации")
    # Start polling
    u.start_polling()
    # Run the bot until the you presses Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    u.idle()


if __name__ == '__main__':
    main()
