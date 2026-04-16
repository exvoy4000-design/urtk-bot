import asyncio
import aiohttp
import json
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from functools import lru_cache
import logging

logging.basicConfig(level=logging.INFO)
API_TOKEN = "8669694007:AAGcuYf86gCLuPxJbxstk56w4rZocZ6DNY0"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Кеш
schedule_cache = {}
cache_time = {}

class UserState(StatesGroup):
    waiting_course = State()
    waiting_group = State()
    waiting_day = State()
    waiting_teacher = State()

def get_weekday_name(day_num):
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    return days[day_num]

async def fetch_json(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=10) as resp:
            return await resp.json()

async def get_groups():
    data = await fetch_json("https://urtk-journal.ru/api/groups/urtk")
    groups_by_course = {}
    for course_idx, course_data in enumerate(data):
        groups_by_course[course_idx + 1] = [g["name"] for g in course_data["groups"]]
    return groups_by_course

@lru_cache(maxsize=100)
async def get_group_id(group_name):
    data = await fetch_json("https://urtk-journal.ru/api/groups/urtk")
    for course in data:
        for group in course["groups"]:
            if group["name"] == group_name:
                return group["id"]
    return None

async def get_schedule(group_id):
    now = datetime.now()
    cache_key = f"schedule_{group_id}"
    if cache_key in schedule_cache and (now - cache_time[cache_key]).seconds < 600:
        return schedule_cache[cache_key]
    data = await fetch_json(f"https://urtk-journal.ru/api/schedule/group/{group_id}")
    schedule_cache[cache_key] = data
    cache_time[cache_key] = now
    return data

def format_schedule(data, target_day, group_name):
    if not data or "schedule" not in data:
        return "Нет расписания"
    
    for day_data in data["schedule"]:
        if day_data["day"] == target_day:
            date_str = day_data.get("date", "")[:5]
            lines = [f"*{date_str} - {target_day} ({group_name})*"]
            for lesson in day_data.get("lessons", []):
                num = lesson.get("number")
                name = lesson.get("name", "").split(" | ")[0].strip()
                office = lesson.get("office", "")
                if name and "Кл. час" not in name:
                    lines.append(f"*{num}*) {name} - {office}")
                elif name:
                    lines.append(f"*{num}*) {name} - {office}")
            return "\n".join(lines)
    return f"Расписание на {target_day} отсутствует"

def format_week_schedule(data, group_name):
    if not data or "schedule" not in data:
        return "Нет расписания"
    
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    week_days = []
    
    for day_data in data["schedule"]:
        if day_data["day"] == "Воскресенье":
            continue
        try:
            date = datetime.strptime(day_data["date"], "%d.%m.%Y")
            if monday <= date <= monday + timedelta(days=6):
                week_days.append(day_data)
        except:
            week_days.append(day_data)
    
    result = []
    for day_data in week_days:
        result.append(format_schedule(data, day_data["day"], group_name))
    return "\n\n".join(result) if result else "Расписание на неделю отсутствует"

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="1 курс"), KeyboardButton(text="2 курс")],
            [KeyboardButton(text="3 курс"), KeyboardButton(text="4 курс")],
            [KeyboardButton(text="Преподаватели")]
        ],
        resize_keyboard=True
    )
    await message.answer("📚 *УРТК Расписание*\nВыберите курс:", parse_mode="Markdown", reply_markup=keyboard)
    await state.set_state(UserState.waiting_course)

@dp.message(UserState.waiting_course)
async def handle_course(message: types.Message, state: FSMContext):
    if message.text == "Преподаватели":
        await message.answer("👨‍🏫 Функция преподавателей в разработке\nВыберите курс:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="1 курс"), KeyboardButton(text="2 курс")], [KeyboardButton(text="3 курс"), KeyboardButton(text="4 курс")]], resize_keyboard=True))
        return
    
    if message.text not in ["1 курс", "2 курс", "3 курс", "4 курс"]:
        await message.answer("Пожалуйста, выберите курс из меню")
        return
    
    course_num = int(message.text[0])
    groups_data = await get_groups()
    groups = groups_data.get(course_num, [])
    
    if not groups:
        await message.answer("Нет групп для этого курса")
        return
    
    await state.update_data(course=course_num)
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    for i in range(0, len(groups), 3):
        keyboard.row(*[KeyboardButton(text=g) for g in groups[i:i+3]])
    keyboard.row(KeyboardButton(text="Назад"))
    
    await message.answer(f"🎓 Выберите группу {course_num} курса:", reply_markup=keyboard)
    await state.set_state(UserState.waiting_group)

@dp.message(UserState.waiting_group)
async def handle_group(message: types.Message, state: FSMContext):
    if message.text == "Назад":
        await start(message, state)
        return
    
    group_name = message.text
    group_id = await get_group_id(group_name)
    
    if not group_id:
        await message.answer("Группа не найдена, выберите из списка")
        return
    
    await state.update_data(group_name=group_name, group_id=group_id)
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Сегодня"), KeyboardButton(text="Завтра")],
            [KeyboardButton(text="Понедельник"), KeyboardButton(text="Вторник")],
            [KeyboardButton(text="Среда"), KeyboardButton(text="Четверг")],
            [KeyboardButton(text="Пятница"), KeyboardButton(text="Суббота")],
            [KeyboardButton(text="Вся неделя"), KeyboardButton(text="Сменить группу")]
        ],
        resize_keyboard=True
    )
    await message.answer(f"✅ Выбрана группа *{group_name}*\nВыберите день:", parse_mode="Markdown", reply_markup=keyboard)
    await state.set_state(UserState.waiting_day)

@dp.message(UserState.waiting_day)
async def handle_day(message: types.Message, state: FSMContext):
    if message.text == "Сменить группу":
        await start(message, state)
        return
    
    user_data = await state.get_data()
    group_name = user_data.get("group_name")
    group_id = user_data.get("group_id")
    
    if not group_id:
        await message.answer("Ошибка: группа не выбрана")
        await start(message, state)
        return
    
    await message.answer("⏳ Загружаю расписание...")
    
    schedule_data = await get_schedule(group_id)
    
    if message.text == "Вся неделя":
        result = format_week_schedule(schedule_data, group_name)
    else:
        target_day = message.text
        if target_day == "Сегодня":
            target_day = get_weekday_name(datetime.now().weekday())
        elif target_day == "Завтра":
            target_day = get_weekday_name((datetime.now() + timedelta(days=1)).weekday())
        result = format_schedule(schedule_data, target_day, group_name)
    
    await message.answer(result, parse_mode="Markdown")
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Сегодня"), KeyboardButton(text="Завтра")],
            [KeyboardButton(text="Понедельник"), KeyboardButton(text="Вторник")],
            [KeyboardButton(text="Среда"), KeyboardButton(text="Четверг")],
            [KeyboardButton(text="Пятница"), KeyboardButton(text="Суббота")],
            [KeyboardButton(text="Вся неделя"), KeyboardButton(text="Сменить группу")]
        ],
        resize_keyboard=True
    )
    await message.answer("📅 Выберите другой день:", reply_markup=keyboard)

@dp.message()
async def fallback(message: types.Message, state: FSMContext):
    await message.answer("Пожалуйста, пользуйтесь кнопками меню")
    await start(message, state)

async def main():
    print("🚀 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())