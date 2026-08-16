import asyncio
import logging
import os
import json
import random
import threading
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions, BotCommand
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import *
from game import Game, Player

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

game: Game = None
gifs: dict = {}
role_history: dict = {}

DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

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

# FSM
class CharacterName(StatesGroup):
    waiting = State()

class Presentation(StatesGroup):
    waiting = State()

class GifScene(StatesGroup):
    waiting = State()

# Вспомогательные функции
async def set_admin_title(chat_id: int, user_id: int, title: str):
    try:
        await bot.promote_chat_member(
            chat_id=chat_id,
            user_id=user_id,
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
            custom_title=title,
        )
        logger.info(f"Set admin title for {user_id}: {title}")
    except Exception as e:
        logger.error(f"Failed to set admin title for {user_id}: {e}")

async def remove_admin(chat_id: int, user_id: int):
    try:
        await bot.demote_chat_member(chat_id=chat_id, user_id=user_id)
        logger.info(f"Removed admin from {user_id}")
    except Exception as e:
        logger.error(f"Failed to demote {user_id}: {e}")

async def mute_all_except_leader():
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
    file_id = gifs.get(scene)
    if file_id:
        try:
            await bot.send_animation(chat_id=chat_id, animation=file_id, caption=caption)
        except Exception as e:
            logger.error(f"Failed to send gif for scene {scene}: {e}")
            await bot.send_message(chat_id, caption)
    else:
        await bot.send_message(chat_id, caption)

# Middleware для удаления сообщений в ночь и голосование
@router.message(F.chat.type.in_({"group", "supergroup"}))
async def delete_messages_in_restricted_phases(message: Message):
    if game and game.phase in ["night", "voting"] and message.from_user.id != LEADER_ID:
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Failed to delete message: {e}")

# Команды ведущего
@router.message(Command("start_game"))
async def cmd_start_game(message: Message):
    global game
    if message.from_user.id != LEADER_ID:
        await message.answer("Эта команда доступна только ведущему.")
        return
    if game and game.phase != "ended":
        await message.answer("Игра уже идёт.")
        return
    game = Game(LEADER_ID, CHAT_ID)
    game.phase = "registration"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Присоединиться", callback_data="join_game")]
    ])
    sent_msg = await message.answer(MSG_WELCOME, reply_markup=keyboard)
    try:
        await bot.pin_chat_message(chat_id=message.chat.id, message_id=sent_msg.message_id)
    except:
        pass
    logger.info("Game started, registration phase")

@router.message(Command("end_game"))
async def cmd_end_game(message: Message):
    global game
    if message.from_user.id != LEADER_ID:
        return
    if game and game.phase != "ended":
        await finish_game()
    await message.answer("Игра завершена.")

@router.message(Command("reset_history"))
async def cmd_reset_history(message: Message):
    global role_history
    if message.from_user.id != LEADER_ID:
        return
    role_history = {}
    save_json("role_history.json", role_history)
    await message.answer("История выданных скрытых ролей сброшена.")

@router.message(Command("set_gif"))
async def cmd_set_gif(message: Message, state: FSMContext):
    if message.from_user.id != LEADER_ID:
        return
    scenes = GIF_SCENES
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=scene, callback_data=f"set_gif_scene:{scene}")] for scene in scenes
    ])
    await message.answer("Выберите сцену для гифки:", reply_markup=keyboard)

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
        await state.clear()
    else:
        await message.answer("Пожалуйста, отправьте именно гифку.")

@router.message(Command("get_chat_id"))
async def cmd_get_chat_id(message: Message):
    if message.from_user.id == LEADER_ID:
        await message.answer(f"ID этого чата: {message.chat.id}")

@router.message(Command("force_start"))
async def cmd_force_start(message: Message):
    if message.from_user.id != LEADER_ID:
        return
    if not game or game.phase != "registration":
        await message.answer("Сейчас нельзя принудительно начать.")
        return
    await force_start_game()

async def force_start_game():
    global game
    if not game or game.phase != "registration":
        return
    to_remove = [uid for uid, p in game.players.items() if not p.character_name or not p.presented]
    for uid in to_remove:
        await kick_player(uid)
    if len(game.get_alive_players()) < 3:
        await bot.send_message(CHAT_ID, "Недостаточно игроков (нужно минимум 3).")
        return
    await start_night_phase()

# Меню
async def send_menu(user_id: int):
    buttons = [
        [KeyboardButton(text="📜 Правила игры")],
        [KeyboardButton(text="👥 Жители")],
        [KeyboardButton(text="🚪 Покинуть игру")],
    ]
    if user_id == LEADER_ID:
        buttons.append([KeyboardButton(text="🎬 Установить гифку")])
        buttons.append([KeyboardButton(text="▶️ Запустить игру")])
        buttons.append([KeyboardButton(text="⏹ Остановить игру")])
        buttons.append([KeyboardButton(text="🔄 Сбросить историю")])
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await bot.send_message(user_id, "Меню игры:", reply_markup=keyboard)

@router.message(CommandStart())
async def cmd_start(message: Message):
    await send_menu(message.from_user.id)

@router.message(Command("menu"))
async def cmd_menu(message: Message):
    await send_menu(message.from_user.id)

@router.message(lambda message: message.text == "📜 Правила игры")
async def button_rules(message: Message):
    await message.answer(RULES_TEXT, parse_mode="Markdown")

@router.message(lambda message: message.text == "👥 Жители")
async def button_players(message: Message):
    if not game:
        await message.answer("Нет активной игры.")
        return
    text = "**Жители:**\n" + "\n".join([f"• {p.character_name or 'Без имени'}" for p in game.players.values()])
    await message.answer(text)

@router.message(lambda message: message.text == "🚪 Покинуть игру")
async def button_leave(message: Message):
    if game and message.from_user.id in game.players:
        await kick_player(message.from_user.id)
        await message.answer("Вы покинули игру.")
    else:
        await message.answer("Вы не участвуете.")

@router.message(lambda message: message.text == "🎬 Установить гифку")
async def button_set_gif(message: Message):
    if message.from_user.id != LEADER_ID:
        return
    scenes = GIF_SCENES
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=scene, callback_data=f"set_gif_scene:{scene}")] for scene in scenes
    ])
    await message.answer("Выберите сцену:", reply_markup=keyboard)

@router.message(lambda message: message.text == "▶️ Запустить игру")
async def button_start_game(message: Message):
    if message.from_user.id != LEADER_ID:
        return
    if game and game.phase == "registration":
        await force_start_game()
    else:
        await message.answer("Сейчас нельзя запустить игру.")

@router.message(lambda message: message.text == "⏹ Остановить игру")
async def button_stop_game(message: Message):
    if message.from_user.id != LEADER_ID:
        return
    if game and game.phase != "ended":
        await finish_game()
    await message.answer("Игра остановлена.")

@router.message(lambda message: message.text == "🔄 Сбросить историю")
async def button_reset_history(message: Message):
    if message.from_user.id != LEADER_ID:
        return
    global role_history
    role_history = {}
    save_json("role_history.json", role_history)
    await message.answer("История сброшена.")

# Присоединение
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
    try:
        await bot.send_message(user_id, "Проверка связи...")
    except:
        await callback.answer("Сначала напишите боту в личку /start", show_alert=True)
        return
    game.add_player(user_id, callback.from_user.username, callback.from_user.first_name)
    await set_admin_title(CHAT_ID, user_id, "Выбирает персонажа...")
    await bot.send_message(user_id, MSG_ASK_CHARACTER)
    await callback.message.edit_text(f"Присоединился: {callback.from_user.full_name}\nВсего жителей: {len(game.players)}")
    await callback.answer()

# Выбор персонажа и представление
@router.message(CharacterName.waiting)
async def character_name_received(message: Message, state: FSMContext):
    if message.from_user.id == LEADER_ID:
        return
    if not game or message.from_user.id not in game.players:
        await message.answer("Вы не участвуете.")
        await state.clear()
        return
    name = message.text.strip()
    if name:
        player = game.players[message.from_user.id]
        player.character_name = name
        await set_admin_title(CHAT_ID, player.user_id, name)
        await message.answer(f"Персонаж: {name}")
        await state.clear()
        await bot.send_message(message.from_user.id, "Теперь представьтесь! Напишите пару слов о себе.")
        await state.set_state(Presentation.waiting)
    else:
        await message.answer("Введите непустое название.")

@router.message(Presentation.waiting)
async def presentation_received(message: Message, state: FSMContext):
    if message.from_user.id == LEADER_ID:
        return
    if not game or message.from_user.id not in game.players:
        await state.clear()
        return
    text = message.text.strip()
    if text:
        player = game.players[message.from_user.id]
        await bot.send_message(CHAT_ID, f"🔹 **{player.character_name}** (@{player.username or 'нет username'}) представляется:\n{text}")
        player.presented = True
        await message.answer("Представление опубликовано!")
        await state.clear()
        if all(p.character_name and p.presented for p in game.players.values()):
            await start_night_phase()
    else:
        await message.answer("Представление не может быть пустым.")

# Ночная фаза
async def start_night_phase():
    global game
    if not game:
        return
    game.phase = "night"
    game.night_actions = {}
    game.klepto_item = None
    game.klepto_awaiting_item = False
    await send_gif(CHAT_ID, "start_game", MSG_ALL_SETTLED)
    try:
        game.assign_hidden_roles(role_history)
        save_json("role_history.json", role_history)
    except ValueError as e:
        await bot.send_message(CHAT_ID, f"Ошибка: {e}")
        await finish_game()
        return
    for role, user_id in game.hidden_roles.items():
        role_text = {
            "klepto": "Вы — **Клептоман**! Ночью выберите комнату и вещь.",
            "komendant": "Вы — **Комендант**! Выберите комнату для проверки.",
            "uborshica": "Вы — **Уборщица**! Выберите комнату для мытья."
        }[role]
        await bot.send_message(user_id, role_text)
        alive = game.get_alive_players()
        targets = [p for p in alive if p.user_id != user_id]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{p.character_name}", callback_data=f"night_choice:{p.user_id}")] for p in targets
        ])
        await bot.send_message(user_id, "Выберите комнату:", reply_markup=keyboard)
    await mute_all_except_leader()
    await send_gif(CHAT_ID, "night", MSG_NIGHT_START)
    asyncio.create_task(night_timeout())

async def night_timeout():
    await asyncio.sleep(NIGHT_ACTION_TIMEOUT)
    if game and game.phase == "night":
        for role, uid in game.hidden_roles.items():
            if role not in game.night_actions:
                alive = game.get_alive_players()
                targets = [p for p in alive if p.user_id != uid]
                if targets:
                    game.night_actions[role] = random.choice(targets).user_id
                    await bot.send_message(uid, f"Вы не выбрали. Выбрано случайно.")
        if game.hidden_roles.get("klepto") and not game.klepto_item:
            game.klepto_item = "что-то загадочное"
            await bot.send_message(game.hidden_roles["klepto"], "Вы не указали вещь, крадём что-то загадочное.")
        await resolve_night()

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
    if len(game.night_actions) == 3:
        klepto_id = game.hidden_roles.get("klepto")
        if game.night_actions.get("klepto") == game.night_actions.get("komendant"):
            await resolve_night()
            return
        if klepto_id and not game.klepto_item:
            victim_name = game.players[game.night_actions["klepto"]].character_name
            await bot.send_message(klepto_id, f"Вы выбрали комнату **{victim_name}**. Какую вещь крадёте?")
            game.klepto_awaiting_item = True
            return
        await resolve_night()

@router.message(lambda message: game and game.klepto_awaiting_item and message.from_user.id == game.hidden_roles.get("klepto"))
async def klepto_item_received(message: Message):
    if not game or game.phase != "night":
        return
    item = message.text.strip()
    if item:
        game.klepto_item = item
        game.klepto_awaiting_item = False
        await message.answer(f"Вы украли: {item}")
        await resolve_night()
    else:
        await message.answer("Вещь не может быть пустой.")

async def resolve_night():
    global game
    if not game or game.phase != "night":
        return
    game.phase = "morning"
    klepto_target = game.night_actions.get("klepto")
    komendant_target = game.night_actions.get("komendant")
    uborshica_target = game.night_actions.get("uborshica")
    game.klepto_caught = (klepto_target is not None and klepto_target == komendant_target)
    if not game.klepto_caught and klepto_target is not None:
        if klepto_target == uborshica_target:
            game.klepto_stole = False
        else:
            game.klepto_stole = True
            game.klepto_stole_from = klepto_target
            if game.klepto_item:
                victim_name = game.players[klepto_target].character_name
                game.stolen_items.append((victim_name, game.klepto_item))
    else:
        game.klepto_stole = False
    await send_gif(CHAT_ID, "morning", MSG_MORNING)
    if game.klepto_caught:
        await bot.send_message(CHAT_ID, "🚨 Комендант поймал клептомана! Игра окончена.")
        game.winner = "residents"
        game.end_reason = "caught"
        await finish_game()
        return
    elif game.klepto_stole:
        victim_name = game.players[game.klepto_stole_from].character_name
        await bot.send_message(CHAT_ID, f"Сегодня ночью клептоман посетил {victim_name} и украл: {game.klepto_item}")
    else:
        await bot.send_message(CHAT_ID, "Сегодня ночью клептоман остался ни с чем.")
    await start_discussion()

async def start_discussion():
    game.phase = "discussion"
    await unmute_all()
    await bot.send_message(CHAT_ID, MSG_DISCUSSION)
    await asyncio.sleep(DISCUSSION_TIME)
    if game and game.phase == "discussion":
        await bot.send_message(CHAT_ID, MSG_VOTE_SOON)
        await asyncio.sleep(60)
        if game and game.phase == "discussion":
            await start_voting()

async def start_voting():
    game.phase = "voting"
    game.vote_results = {}
    await mute_all_except_leader()
    await bot.send_message(CHAT_ID, "СТОП ЧАТ")
    await bot.send_message(CHAT_ID, MSG_VOTE_NOW)
    alive = game.get_alive_players()
    for player in game.players.values():
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{p.character_name}", callback_data=f"vote:{p.user_id}")] for p in alive if p.user_id != player.user_id
        ])
        await bot.send_message(player.user_id, "Голосуйте:", reply_markup=keyboard)
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
    voter = callback.from_user.id
    target = int(callback.data.split(":")[1])
    if voter not in game.players:
        await callback.answer("Вы не участник.")
        return
    game.vote_results[voter] = target
    await callback.message.edit_text("Голос учтён.")
    await callback.answer()
    if len(game.vote_results) == len(game.players):
        await end_voting()

async def end_voting():
    if not game or game.phase != "voting":
        return
    game.phase = "results"
    vote_count = {}
    for target in game.vote_results.values():
        vote_count[target] = vote_count.get(target, 0) + 1
    if vote_count:
        max_votes = max(vote_count.values())
        top = [uid for uid, count in vote_count.items() if count == max_votes]
        chosen = random.choice(top)
    else:
        chosen = None
    await unmute_all()
    if chosen:
        victim = game.players[chosen]
        phrase = random.choice(VOTE_RESULTS)
        await bot.send_message(CHAT_ID, phrase.format(name=victim.character_name))
        victim.is_alive = False
        klepto_id = game.hidden_roles.get("klepto")
        if chosen == klepto_id:
            items_list = ", ".join([item for _, item in game.stolen_items]) if game.stolen_items else "ничего"
            await bot.send_message(CHAT_ID, f"Под матрасом клептомана нашли: {items_list}!")
            game.winner = "residents"
            game.end_reason = "vote"
            await finish_game()
            return
        winner = game.check_win_condition()
        if winner:
            game.winner = winner
            await finish_game()
            return
        await start_night_phase()
    else:
        await bot.send_message(CHAT_ID, "Никто не проголосовал, день пропущен.")
        await start_night_phase()

async def finish_game():
    global game
    if not game:
        return
    for uid in game.players:
        await remove_admin(CHAT_ID, uid)
    await unmute_all()
    if game.winner == "klepto":
        pobediteli = MSG_KLEPTO_WIN
    else:
        pobediteli = MSG_RESIDENTS_WIN
    roles_info = []
    for role, uid in game.hidden_roles.items():
        player = game.players.get(uid)
        if player:
            role_name = {"klepto": "Клептоман🥷", "komendant": "Комендант 🕵️", "uborshica": "Уборщица 🧑‍🦳"}[role]
            roles_info.append(f"{player.character_name} — {role_name}")
    roles_text = "\n".join(roles_info) if roles_info else "Скрытые роли не назначены."
    others = [p.character_name for p in game.players.values() if p.hidden_role is None]
    others_text = "\n".join(others) if others else "Нет."
    stolen_block = ""
    if game.end_reason != "vote" and game.stolen_items:
        stolen_lines = "\n".join([f"• {item} (у {victim})" for victim, item in game.stolen_items])
        stolen_block = f"\n\n🛍️ Украденные вещи:\n{stolen_lines}"
    final_text = MSG_GAME_END.format(pobediteli=pobediteli, roles=roles_text, others=others_text) + stolen_block
    await send_gif(CHAT_ID, "game_end", final_text)
    game.phase = "ended"
    logger.info("Game finished")

async def kick_player(user_id: int):
    if not game or user_id not in game.players:
        return
    await remove_admin(CHAT_ID, user_id)
    game.remove_player(user_id)
    try:
        await bot.ban_chat_member(chat_id=CHAT_ID, user_id=user_id, revoke_messages=False)
        await bot.unban_chat_member(chat_id=CHAT_ID, user_id=user_id)
    except Exception as e:
        logger.error(f"Failed to kick {user_id}: {e}")
    for role, uid in list(game.hidden_roles.items()):
        if uid == user_id:
            del game.hidden_roles[role]
            await bot.send_message(CHAT_ID, f"Игрок покинул игру, освободилась скрытая роль {role}.")
    winner = game.check_win_condition()
    if winner and game.phase != "ended":
        game.winner = winner
        await finish_game()

@router.message(Command("kick"))
async def cmd_kick(message: Message):
    if message.from_user.id != LEADER_ID:
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /kick @username")
        return
    username = args[1].lstrip('@')
    target = None
    for uid, p in game.players.items():
        if p.username and p.username.lower() == username.lower():
            target = uid
            break
    if target:
        await kick_player(target)
        await message.answer(f"Игрок @{username} удалён.")
    else:
        await message.answer("Игрок не найден.")

# Запуск
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="menu", description="Показать меню"),
        BotCommand(command="start_game", description="Запустить игру (ведущий)"),
        BotCommand(command="force_start", description="Принудительно начать (ведущий)"),
        BotCommand(command="end_game", description="Остановить игру"),
        BotCommand(command="reset_history", description="Сбросить историю ролей"),
        BotCommand(command="set_gif", description="Установить гифку"),
        BotCommand(command="kick", description="Кикнуть игрока"),
        BotCommand(command="get_chat_id", description="Узнать ID чата"),
    ]
    await bot.set_my_commands(commands)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
