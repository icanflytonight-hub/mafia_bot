# bot.py

import asyncio
import logging
import os
import json
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import *
from game import Game, Player

# ---------- Настройка логирования ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Инициализация ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Глобальные переменные
game: Game = None
gifs: dict = {}
role_history: dict = {}

# Папка для данных
DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# Загрузка сохранённых данных
def load_json(filename, default):
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return default
    return default

def save_json(filename, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

gifs = load_json("gifs.json", {})
role_history = load_json("role_history.json", {})

# ---------- FSM состояния ----------
class CharacterName(StatesGroup):
    waiting = State()

class GifScene(StatesGroup):
    waiting = State()

# ---------- Вспомогательные функции ----------
async def set_admin_title(chat_id: int, user_id: int, title: str):
    """Выдаёт временную админку с custom_title, все права выключены."""
    try:
        await bot.promote_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            rights=None,  # в новых версиях aiogram можно передать ChatAdministratorRights с False
            custom_title=title,
            is_anonymous=False,
            can_manage_chat=False,
            can_post_messages=False,
            can_edit_messages=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False,
            can_post_stories=False,
            can_edit_stories=False,
            can_delete_stories=False,
        )
        logger.info(f"Set admin title for {user_id}: {title}")
    except Exception as e:
        logger.error(f"Failed to set admin title for {user_id}: {e}")

async def remove_admin(chat_id: int, user_id: int):
    """Снимает временную админку (понижает до обычного участника)."""
    try:
        await bot.demote_chat_member(chat_id=chat_id, user_id=user_id)
        logger.info(f"Removed admin from {user_id}")
    except Exception as e:
        logger.error(f"Failed to demote {user_id}: {e}")

async def mute_all_except_leader():
    """Мьютит всех игроков, кроме ведущего и бота."""
    if not game:
        return
    for user_id in game.players:
        if user_id != LEADER_ID:
            try:
                await bot.restrict_chat_member(
                    chat_id=CHAT_ID,
                    user_id=user_id,
                    permissions=ChatPermissions(can_send_messages=False, can_send_media_messages=False, can_send_other_messages=False)
                )
            except Exception as e:
                logger.error(f"Failed to mute {user_id}: {e}")

async def unmute_all():
    """Снимает мут со всех игроков."""
    if not game:
        return
    for user_id in game.players:
        try:
            await bot.restrict_chat_member(
                chat_id=CHAT_ID,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True)
            )
        except Exception as e:
            logger.error(f"Failed to unmute {user_id}: {e}")

async def send_gif(chat_id: int, scene: str, caption: str = ""):
    """Отправляет гифку по file_id, если она сохранена."""
    file_id = gifs.get(scene)
    if file_id:
        try:
            await bot.send_animation(chat_id=chat_id, animation=file_id, caption=caption)
        except Exception as e:
            logger.error(f"Failed to send gif for scene {scene}: {e}")
            await bot.send_message(chat_id, caption)
    else:
        await bot.send_message(chat_id, caption)

# ---------- Обработчики команд (только для ведущего) ----------

@router.message(Command("start_game"))
async def cmd_start_game(message: Message):
    global game
    if message.from_user.id != LEADER_ID:
        await message.answer("Эта команда доступна только ведущему.")
        return
    if message.chat.id != CHAT_ID:
        await message.answer("Команду /start_game нужно отправлять в игровом чате.")
        return
    if game and game.phase != "ended":
        await message.answer("Игра уже идёт. Завершите её командой /end_game.")
        return

    game = Game(LEADER_ID, CHAT_ID)
    game.phase = "registration"

    # Отправляем сообщение с кнопкой
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Присоединиться", callback_data="join_game")]
    ])
    sent = await send_gif(CHAT_ID, "start_game", MSG_WELCOME)
    # Если send_gif отправил только текст, но мы хотим заменить на сообщение с кнопкой? Нет, лучше отдельно.
    # Проблема: send_gif отправляет сообщение с гифкой, но кнопку в caption не добавить.
    # Поэтому для приглашения используем обычное сообщение с кнопкой, а гифку можно отправить отдельно.
    # Решение: отправим сначала сообщение с кнопкой, а гифку как отдельное.
    if gifs.get("start_game"):
        await bot.send_animation(CHAT_ID, animation=gifs["start_game"], caption=MSG_WELCOME, reply_markup=keyboard)
    else:
        await message.answer(MSG_WELCOME, reply_markup=keyboard)

    game.registration_message_id = sent.message_id if sent else None
    logger.info("Game started, registration phase")

@router.message(Command("end_game"))
async def cmd_end_game(message: Message):
    global game
    if message.from_user.id != LEADER_ID:
        await message.answer("Только для ведущего.")
        return
    if game and game.phase != "ended":
        await finish_game()
    await message.answer("Игра завершена.")

@router.message(Command("reset_history"))
async def cmd_reset_history(message: Message):
    global role_history
    if message.from_user.id != LEADER_ID:
        await message.answer("Только для ведущего.")
        return
    role_history = {}
    save_json("role_history.json", role_history)
    await message.answer("История выданных скрытых ролей сброшена.")

@router.message(Command("set_gif"))
async def cmd_set_gif(message: Message, state: FSMContext):
    if message.from_user.id != LEADER_ID:
        await message.answer("Только для ведущего.")
        return
    # Предлагаем выбрать сцену
    scenes = GIF_SCENES
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=scene, callback_data=f"set_gif_scene:{scene}")] for scene in scenes
    ])
    await message.answer("Выберите сцену, для которой хотите установить гифку:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("set_gif_scene:"))
async def process_gif_scene(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != LEADER_ID:
        await callback.answer("Нет прав.")
        return
    scene = callback.data.split(":")[1]
    await state.update_data(scene=scene)
    await state.set_state(GifScene.waiting)
    await callback.message.answer(f"Отправьте гифку для сцены «{scene}».")
    await callback.answer()

@router.message(GifScene.waiting)
async def receive_gif(message: Message, state: FSMContext):
    if message.from_user.id != LEADER_ID:
        return
    if message.animation:
        data = await state.get_data()
        scene = data.get("scene")
        if scene:
            gifs[scene] = message.animation.file_id
            save_json("gifs.json", gifs)
            await message.answer(f"Гифка для сцены «{scene}» сохранена!")
        else:
            await message.answer("Ошибка: не выбрана сцена.")
        await state.clear()
    else:
        await message.answer("Пожалуйста, отправьте именно гифку (анимацию).")

@router.message(Command("get_chat_id"))
async def cmd_get_chat_id(message: Message):
    if message.from_user.id == LEADER_ID:
        await message.answer(f"ID этого чата: {message.chat.id}")

# ---------- Обработчики для игроков ----------

@router.message(CommandStart())
async def cmd_start(message: Message):
    await send_menu(message.from_user.id)

async def send_menu(user_id: int):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Правила игры", callback_data="menu_rules")],
        [InlineKeyboardButton(text="👥 Активные игроки", callback_data="menu_players")],
        [InlineKeyboardButton(text="🚪 Покинуть игру", callback_data="menu_leave")]
    ])
    await bot.send_message(user_id, "Меню игры:", reply_markup=keyboard)

@router.message(Command("menu"))
async def cmd_menu(message: Message):
    await send_menu(message.from_user.id)

@router.callback_query(F.data == "menu_rules")
async def show_rules(callback: CallbackQuery):
    await callback.message.answer(RULES_TEXT, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "menu_players")
async def show_players(callback: CallbackQuery):
    if not game:
        await callback.message.answer("Сейчас нет активной игры.")
        await callback.answer()
        return
    alive = [p for p in game.players.values() if p.is_alive]
    dead = [p for p in game.players.values() if not p.is_alive]
    text = "**Участники:**\n"
    text += "\n".join([f"• {p.character_name or 'Без имени'}" for p in game.players.values()])
    if dead:
        text += "\n\nВыбывшие:\n" + "\n".join([f"• {p.character_name or 'Без имени'}" for p in dead])
    await callback.message.answer(text)
    await callback.answer()

@router.callback_query(F.data == "menu_leave")
async def leave_game(callback: CallbackQuery):
    if game and callback.from_user.id in game.players:
        await kick_player(callback.from_user.id)
        await callback.message.answer("Вы покинули игру.")
    else:
        await callback.message.answer("Вы не участвуете в игре.")
    await callback.answer()

# ---------- Присоединение к игре ----------

@router.callback_query(F.data == "join_game")
async def join_game(callback: CallbackQuery):
    global game
    if not game or game.phase != "registration":
        await callback.answer("Сейчас нельзя присоединиться.")
        return
    user_id = callback.from_user.id
    if user_id == LEADER_ID:
        await callback.answer("Ведущий не может участвовать.", show_alert=True)
        return
    if user_id in game.players:
        await callback.answer("Вы уже участвуете.")
        return

    # Проверяем, писал ли бот игроку в личку (просто отправим сообщение)
    try:
        await bot.send_message(user_id, "Проверка связи... Если вы видите это сообщение, всё хорошо.")
    except:
        await callback.answer("Сначала напишите боту в личные сообщения /start", show_alert=True)
        return

    game.add_player(user_id, callback.from_user.username, callback.from_user.first_name)
    # Выдаём временную админку с заглушкой "Выбирает персонажа..."
    await set_admin_title(CHAT_ID, user_id, "Выбирает персонажа...")
    # Отправляем запрос на ввод персонажа
    await bot.send_message(user_id, MSG_ASK_CHARACTER)
    # Обновляем сообщение в группе (можно отредактировать или отправить новое)
    await callback.message.edit_text(
        f"Присоединился: {callback.from_user.full_name}\nВсего игроков: {len(game.players)}",
        reply_markup=callback.message.reply_markup
    )
    await callback.answer()

# ---------- Ввод персонажа (свободный текст) ----------

@router.message(CharacterName.waiting)
async def character_name_received(message: Message, state: FSMContext):
    if message.from_user.id == LEADER_ID:
        return
    if game and message.from_user.id in game.players:
        player = game.players[message.from_user.id]
        name = message.text.strip()
        if name:
            player.character_name = name
            await set_admin_title(CHAT_ID, player.user_id, name)
            await message.answer(f"Отлично! Ваш персонаж: {name}")
            await state.clear()
            # Проверяем, все ли выбрали персонажа
            if all(p.character_name for p in game.players.values()):
                await start_night_phase()
        else:
            await message.answer("Пожалуйста, введите непустое название.")
    else:
        await message.answer("Вы не участвуете в игре.")

# ---------- Ночная фаза ----------

async def start_night_phase():
    global game
    if not game:
        return
    game.phase = "night"
    # 1. Объявляем расселение (уже было? нет, это перед ночью)
    # Уже отправлено "Все жители расселились..." при старте? В требованиях это сообщение идёт после выбора персонажей, перед отбоем.
    await send_gif(CHAT_ID, "start_game", MSG_ALL_SETTLED)  # используем scene "start_game" для расселения? Лучше отдельный.
    # Назначаем скрытые роли
    try:
        game.assign_hidden_roles(role_history)
        save_json("role_history.json", role_history)
    except ValueError as e:
        await bot.send_message(CHAT_ID, f"Ошибка: {e}")
        await finish_game()
        return
    # Отправляем роли в личку
    for role, user_id in game.hidden_roles.items():
        role_text = {
            "klepto": "Вы — **Клептоман**! Ваша цель — выжить до конца, пока не останется два игрока. Ночью выберите комнату (живого игрока) для кражи.",
            "komendant": "Вы — **Комендант**! Ваша цель — найти клептомана. Ночью выберите комнату для проверки. Если выберете ту же, что и клептоман, он будет пойман.",
            "uborshica": "Вы — **Уборщица**! Ваша цель — помешать клептоману. Ночью выберите комнату для мытья. Если клептоман выберет ту же комнату, кража не состоится."
        }[role]
        await bot.send_message(user_id, role_text)
        # Отправляем клавиатуру выбора комнаты
        alive_players = game.get_alive_players()
        # Исключаем самого себя, если роль не клептоман? В правилах клептоман не может выбрать свою комнату, так как он живёт в комнате, но не сказано явно. Для всех ролей исключаем собственную комнату.
        targets = [p for p in alive_players if p.user_id != user_id]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{p.character_name}", callback_data=f"night_choice:{p.user_id}")] for p in targets
        ])
        await bot.send_message(user_id, "Выберите комнату (игрока):", reply_markup=keyboard)

    # Мьютим чат
    await mute_all_except_leader()
    # Отправляем ночное сообщение с гифкой
    await send_gif(CHAT_ID, "night", MSG_NIGHT_START)
    # Устанавливаем таймер на ночные действия (если не все ответят, принудительно завершим)
    # Реализуем через asyncio.create_task
    asyncio.create_task(night_timeout())

async def night_timeout():
    await asyncio.sleep(NIGHT_ACTION_TIMEOUT)
    if game and game.phase == "night":
        # Если не все скрытые роли выбрали, делаем случайный выбор
        for role, user_id in game.hidden_roles.items():
            if user_id not in game.night_actions:
                alive = game.get_alive_players()
                targets = [p for p in alive if p.user_id != user_id]
                if targets:
                    random_target = random.choice(targets).user_id
                    game.night_actions[role] = random_target
                    await bot.send_message(user_id, f"Вы не выбрали комнату. Выбрана случайно: {game.players[random_target].character_name}")
        await resolve_night()

# Обработка выбора комнаты ночью
@router.callback_query(F.data.startswith("night_choice:"))
async def night_choice(callback: CallbackQuery):
    if not game or game.phase != "night":
        await callback.answer("Сейчас не ночь.")
        return
    user_id = callback.from_user.id
    role = game.get_hidden_role_info(user_id)
    if not role:
        await callback.answer("Вы не скрытая роль.")
        return
    target_id = int(callback.data.split(":")[1])
    game.night_actions[role] = target_id
    await callback.message.edit_text(f"Вы выбрали: {game.players[target_id].character_name}")
    await callback.answer()
    # Если все три роли выбрали, завершаем ночь
    if len(game.night_actions) == 3:
        await resolve_night()

async def resolve_night():
    global game
    if not game or game.phase != "night":
        return
    game.phase = "morning"
    # Получаем действия
    klepto_target = game.night_actions.get("klepto")
    komendant_target = game.night_actions.get("komendant")
    uborshica_target = game.night_actions.get("uborshica")

    # Проверяем поимку комендантом
    game.klepto_caught = (klepto_target is not None and klepto_target == komendant_target)

    # Проверяем уборку
    if not game.klepto_caught and klepto_target is not None:
        if klepto_target == uborshica_target:
            game.klepto_stole = False  # не смог украсть
        else:
            game.klepto_stole = True
            game.klepto_stole_from = klepto_target
    else:
        game.klepto_stole = False

    # Снимаем мут
    await unmute_all()

    # Отправляем утреннее сообщение
    await send_gif(CHAT_ID, "morning", MSG_MORNING)

    # Сообщения о действиях скрытых ролей (по желанию можно разбить)
    if game.klepto_target:
        # можно отправить сначала "Клептоман уже выбрал комнату..." и т.д., но уже поздно, они были в предыдущих сообщениях.
        pass

    # Объявляем результаты ночи
    if game.klepto_caught:
        await bot.send_message(CHAT_ID, "🚨 Комендант поймал клептомана в комнате! Игра окончена.")
        game.winner = "residents"
        await finish_game()
        return
    elif game.klepto_stole:
        victim_name = game.players[game.klepto_stole_from].character_name
        await bot.send_message(CHAT_ID, f"Сегодня ночью клептоман посетил {victim_name} и украл его вещь.")
    else:
        await bot.send_message(CHAT_ID, "Сегодня ночью клептоман остался ни с чем (или не смог украсть).")

    # Переходим к обсуждению
    await start_discussion()

async def start_discussion():
    game.phase = "discussion"
    await bot.send_message(CHAT_ID, MSG_DISCUSSION)
    # Запускаем таймер обсуждения
    await asyncio.sleep(DISCUSSION_TIME)
    if game and game.phase == "discussion":
        await bot.send_message(CHAT_ID, MSG_VOTE_SOON)
        await asyncio.sleep(60)
        if game and game.phase == "discussion":
            await start_voting()

async def start_voting():
    game.phase = "voting"
    game.vote_results = {}
    game.vote_count = {}
    # СТОП ЧАТ
    await mute_all_except_leader()
    await bot.send_message(CHAT_ID, "СТОП ЧАТ")
    await bot.send_message(CHAT_ID, MSG_VOTE_NOW)
    # Рассылаем голосование всем игрокам
    alive = game.get_alive_players()
    for player in game.players.values():
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{p.character_name}", callback_data=f"vote:{p.user_id}")] for p in alive if p.user_id != player.user_id  # можно голосовать за себя? Обычно нет. Исключаем себя.
        ])
        await bot.send_message(player.user_id, "Голосуйте за подозреваемого:", reply_markup=keyboard)
    # Запускаем таймер голосования
    asyncio.create_task(vote_timeout())

async def vote_timeout():
    await asyncio.sleep(VOTE_TIME)
    if game and game.phase == "voting":
        await end_voting()

@router.callback_query(F.data.startswith("vote:"))
async def vote_callback(callback: CallbackQuery):
    if not game or game.phase != "voting":
        await callback.answer("Сейчас не голосование.")
        return
    voter_id = callback.from_user.id
    target_id = int(callback.data.split(":")[1])
    if voter_id not in game.players:
        await callback.answer("Вы не участник.")
        return
    game.vote_results[voter_id] = target_id
    await callback.message.edit_text("Ваш голос учтён.")
    await callback.answer()
    # Если все проголосовали
    if len(game.vote_results) == len(game.players):
        await end_voting()

async def end_voting():
    if not game or game.phase != "voting":
        return
    game.phase = "results"
    # Считаем голоса
    vote_count = {}
    for target_id in game.vote_results.values():
        vote_count[target_id] = vote_count.get(target_id, 0) + 1
    # Находим игрока с максимальным числом голосов
    if vote_count:
        max_votes = max(vote_count.values())
        top = [uid for uid, count in vote_count.items() if count == max_votes]
        if len(top) > 1:
            # Ничья, можно выбрать случайного или пропустить. По правилам не указано. Сделаем переголосование? Просто выберем случайного.
            chosen = random.choice(top)
        else:
            chosen = top[0]
    else:
        chosen = None

    # Снимаем мут
    await unmute_all()

    if chosen is not None:
        victim = game.players[chosen]
        await bot.send_message(CHAT_ID, MSG_VOTE_RESULT.format(name=victim.character_name))
        # Поднимаем матрас
        victim.is_alive = False
        # Проверяем победу
        winner = game.check_win_condition()
        if winner:
            game.winner = winner
            await finish_game()
            return
        # Если клептоман не пойман, продолжаем: новая ночь
        await start_night_phase()
    else:
        await bot.send_message(CHAT_ID, "Никто не проголосовал. Пропускаем день.")
        await start_night_phase()

async def finish_game():
    global game
    if not game:
        return
    # Снимаем все временные админки
    for user_id in game.players:
        await remove_admin(CHAT_ID, user_id)
    # Снимаем мут (если был)
    await unmute_all()
    # Формируем итоговое сообщение
    if game.winner == "klepto":
        pobediteli = MSG_KLEPTO_WIN
    else:
        pobediteli = MSG_RESIDENTS_WIN

    # Информация о скрытых ролях
    roles_info = []
    for role, uid in game.hidden_roles.items():
        player = game.players.get(uid)
        if player:
            role_name = {
                "klepto": "Клептоман🥷",
                "komendant": "Комендант 🕵️",
                "uborshica": "Уборщица 🧑‍🦳"
            }[role]
            roles_info.append(f"{player.character_name} — {role_name}")
    roles_text = "\n".join(roles_info) if roles_info else "Скрытые роли не назначены."

    others = [p.character_name for p in game.players.values() if p.hidden_role is None]
    others_text = "\n".join(others) if others else "Нет."

    final_text = MSG_GAME_END.format(
        pobediteli=pobediteli,
        roles=roles_text,
        others=others_text
    )
    await send_gif(CHAT_ID, "game_end", final_text)
    game.phase = "ended"
    # Очищаем game? Можно оставить, но разрешить новую игру.
    logger.info("Game finished")

# ---------- Кик игрока ----------

async def kick_player(user_id: int):
    """Удаляет игрока из игры и из группы."""
    if not game or user_id not in game.players:
        return
    # Если игрок - скрытая роль, сообщим
    if game.get_hidden_role_info(user_id):
        # Можно пересоздать или просто отметить, что роль выбыла
        pass
    # Снимаем админку
    await remove_admin(CHAT_ID, user_id)
    # Удаляем из игры
    game.remove_player(user_id)
    # Баним и сразу разбаниваем, чтобы удалить из чата
    try:
        await bot.ban_chat_member(chat_id=CHAT_ID, user_id=user_id, revoke_messages=False)
        await bot.unban_chat_member(chat_id=CHAT_ID, user_id=user_id)
    except Exception as e:
        logger.error(f"Failed to kick {user_id}: {e}")
    # Если игрок был скрытой ролью и игра продолжается, можно назначить замену или пометить
    # Для простоты: если роль была, оставить пустой и уведомить ведущего.
    for role, uid in list(game.hidden_roles.items()):
        if uid == user_id:
            del game.hidden_roles[role]
            await bot.send_message(CHAT_ID, f"Внимание! {game.players[user_id].character_name} покинул игру, освободилась скрытая роль {role}.")
            # Можно пересоздать роль среди оставшихся, но это сложно. Пока просто пропустим.

    # Если игрок был единственным живым, возможно, нужно проверить победу
    winner = game.check_win_condition()
    if winner and game.phase != "ended":
        game.winner = winner
        await finish_game()

# ---------- Команда для кика вручную (опционально) ----------
@router.message(Command("kick"))
async def cmd_kick(message: Message):
    if message.from_user.id != LEADER_ID:
        return
    # Формат: /kick @username
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /kick @username")
        return
    username = args[1].lstrip('@')
    # Найти игрока по username
    target_id = None
    for uid, p in game.players.items():
        if p.username and p.username.lower() == username.lower():
            target_id = uid
            break
    if target_id:
        await kick_player(target_id)
        await message.answer(f"Игрок @{username} удалён из игры и из чата.")
    else:
        await message.answer("Игрок не найден.")

# ---------- Запуск бота ----------

async def main():
    # Устанавливаем вебхук (если используется webapp.py, то там)
    await bot.delete_webhook(drop_pending_updates=True)
    # В webapp.py мы установим вебхук
    await dp.start_polling(bot)  # для локального запуска, но не используется при webhook