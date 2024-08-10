import discord
from discord.ext import commands
import datetime
import math
import pickle
import pytz

# 디스코드 봇 토큰
TOKEN = ''

# 봇 설정 (Privileged Intents 포함)
intents = discord.Intents.default()
intents.message_content = True  # 메시지 내용 읽기 인텐트
intents.presences = True  # 프레즌스 인텐트
intents.members = True  # 멤버 인텐트

bot = commands.Bot(command_prefix='$', intents=intents)

global betting_active
global match_active

# 유저 {points_name} 데이터 저장
user_points = {}
current_bets = {}
user_last_attendance = {}
first_user = None
points_name = '미네랄'
required_role_name = '배팅관리자'

#region save/load/config
config = {
    "출석" : 2000,
    "분당접속" : 25,
    "최대접속시간" : 3,
    "송금수수료비율" : 10,
    "송금회수제한" : 3,
    "승리자점수비율" : 10,
    "패배자점수비율" : 0,
    "승리자기본점수" : 1000,
    "패배자기본점수" : 1000,
    "최소베팅점수" : 500,
    "최대베팅점수" : 10000,
}

# 봇이 시작될 때 {points_name} 데이터를 불러오기
@bot.event
async def on_ready():
    load_user_data()
    print(f'Logged in as {bot.user}')

# 저장 함수
def save_user_points():
    with open('user_points.pkl', 'wb') as file:
        pickle.dump(user_points, file)
    
def save_first_user():
    with open('first_user.pkl', 'wb') as file:
        pickle.dump(first_user, file)

def save_config():
    with open('config.pkl', 'wb') as file:
        pickle.dump(config, file)

# 외부 파일에서 데이터를 불러오는 함수
def load_user_data():
    global user_points
    global first_user
    global config
    try:
        with open('user_points.pkl', 'rb') as file:
            user_points = pickle.load(file)
    except FileNotFoundError:
        user_points = {}

    try:
        with open('first_user.pkl', 'rb') as file:
            first_user = pickle.load(file)
    except FileNotFoundError:
        first_user = None

    try:
        with open('config.pkl', 'rb') as file:
            config = pickle.load(file)
    except FileNotFoundError:
        config = {
            "출석" : 10000,
            "분당접속" : 25,
            "최대접속시간" : 12,
            "송금수수료비율" : 10,
            "송금회수제한" : 3,
            "승리자점수비율" : 10,
            "패배자점수비율" : 1,
            "승리자기본점수" : 5000,
            "패배자기본점수" : 1000,
            "최소베팅점수" : 10000,
            "최대베팅점수" : 500000,
        }

# 함수를 호출할 수 있는 역할을 가진 사용자 확인
def has_required_role(ctx):
    required_role = discord.utils.get(ctx.guild.roles, name=required_role_name)
    if required_role in ctx.author.roles:
        return True
    return False

@bot.command(name='설정', help='봇의 설정 값을 수정합니다. 사용법: $설정 [설정명] [값], 권한 : 관리자')
@commands.has_permissions(administrator=True)
async def set_config(ctx, setting: str, value: int):
    global config
    if setting not in config:
        await ctx.send(f'잘못된 설정명입니다. 사용 가능한 설정명: {list(config.keys())}')
        return
    
    config[setting] = value
    save_config()
    await ctx.send(f'설정 값이 수정되었습니다: {setting} = {value}')

# 설정 값 확인
@bot.command(name='설정확인', help='봇의 설정 값을 확인합니다.')
async def show_config(ctx):
    global config
    config_message = "현재 설정 값:\n"
    for key, value in config.items():
        config_message += f'{key}: {value}\n'
    await ctx.send(config_message)
#endregion save/load/config

def choose_postposition(word, josa_pair):
    # 조사 쌍에서 두 조사를 분리
    josa1, josa2 = josa_pair

    last_char = word[-1]
    # 한글 범위에 있는지 확인
    if '가' <= last_char <= '힣':
        # 받침 유무를 판단
        if (ord(last_char) - ord('가')) % 28 != 0:
            return josa1  # 받침이 있으면 첫 번째 조사
        else:
            return josa2  # 받침이 없으면 두 번째 조사
    else:
        # 한글이 아닌 경우 두 번째 조사를 기본으로 사용
        return josa2

def word_plus_josa(word, josa_pair):
    return "{}{}".format(word, choose_postposition(word, josa_pair))

#region points
# 유저 {points_name} 확인
@bot.command(name=points_name, help=f'자신의 {word_plus_josa(points_name, ("을", "를"))} 확인합니다.')
async def points(ctx):
    user = ctx.author
    points = user_points.get(user.id, 0)

    message = f'{user.mention}님, 당신의 {word_plus_josa(points_name, ("은", "는"))} {points} {points_name}입니다.\n'

    user_bets = current_bets_sorted_by_user.get(user.id, None)

    if user_bets is not None:
        message += '    - 현재 베팅 내역\n'
        for match in current_bets_sorted_by_user[user.id]:
            option = current_bets_sorted_by_user[user.id][match]['option']
            points = current_bets_sorted_by_user[user.id][match]['points']
            message += f'       매치 - {match}의 {option} : {points} {points_name}\n'
        
    await ctx.send(message)

# 유저별 하루 송금 사용 횟수 저장
user_transfer_counts = {}

# 유저 간 {points_name} 송금
@bot.command(name='송금', help=f'다른 유저에게 {word_plus_josa(points_name, ("을", "를"))} 송금합니다. 수수료는 {config["송금수수료비율"]}%입니다. 사용법: $송금 [유저] [{points_name}]')
async def transfer_points(ctx, member_name: str, points: int):
    sender = ctx.author

    try:
        # 멤버를 가져오려고 시도
        member = await commands.MemberConverter().convert(ctx, member_name)
    except commands.MemberNotFound:
        await ctx.send(f'유저 "{word_plus_josa(member_name, ("을", "를"))}" 찾을 수 없습니다.')
        return
    
    user_id = sender.id

    # 현재 시간 (UTC)
    now_utc = datetime.datetime.now(pytz.utc)

    # 한국 시간대 (UTC+9)
    kst = pytz.timezone('Asia/Seoul')

    # 한국 시간대로 변환
    now_kst = now_utc.astimezone(kst)

    # 오늘 자정 KST
    today_kst_midnight = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)

    # 유저가 오늘 사용한 송금 횟수 확인
    if user_id in user_transfer_counts:
        if user_transfer_counts[user_id]['date'] != today_kst_midnight:
            # 오늘 처음 송금하는 경우 초기화
            user_transfer_counts[user_id] = {'count': 0, 'date': today_kst_midnight}
    else:
        # 처음 송금하는 경우 초기화
        user_transfer_counts[user_id] = {'count': 0, 'date': today_kst_midnight}

    # 사용 횟수 체크
    if user_transfer_counts[user_id]['count'] >= config['송금회수제한']:
        await ctx.send('하루에 2회 이상 송금할 수 없습니다.')
        return

    sender_points = user_points.get(sender.id, 0)
    receiver_points = user_points.get(member.id, 0)

    if points <= 0:
        await ctx.send(f'송금할 {word_plus_josa(points_name, ("은", "는"))} 0보다 커야 합니다.')
        return

    if sender.id == member.id:
        await ctx.send(f'자기 자신에게 {word_plus_josa(points_name, ("을", "를"))} 송금할 수 없습니다.')
        return

    if sender_points < points:
        await ctx.send(f'{word_plus_josa(points_name, ("이", "가"))} 부족합니다.')
        return

    user_points[sender.id] = sender_points - points
    user_points[member.id] = receiver_points + math.floor(points * (100 - config['송금수수료비율']) / 100)
    save_user_points()

    # 사용 횟수 증가 및 저장
    user_transfer_counts[user_id]['count'] += 1

    await ctx.send(f'{sender.mention}님이 {member.mention}님에게 {points} {word_plus_josa(points_name, ("을", "를"))} 송금했습니다. 오늘의 남은 송금 회수 : {config["송금회수제한"] - user_transfer_counts[user_id]["count"]}회')

# {points_name} 추가 (관리자 전용)
@bot.command(name='추가', help=f'유저에게 {word_plus_josa(points_name, ("을", "를"))} 추가합니다. $추가 [유저] [{points_name}]')
@commands.has_permissions(administrator=True)
async def addpoints(ctx, member_name: str, points: int):
    try:
        # 멤버를 가져오려고 시도
        member = await commands.MemberConverter().convert(ctx, member_name)
    except commands.MemberNotFound:
        await ctx.send(f'유저 "{word_plus_josa(member_name, ("을", "를"))}" 찾을 수 없습니다.')
        return

    user_points[member.id] = user_points.get(member.id, 0) + points
    save_user_points()
    await ctx.send(f'{member.mention}님에게 {points} {word_plus_josa(points_name, ("을", "를"))} 추가했습니다. 현재 {points_name}: {user_points[member.id]}{points_name}')

# 출석 체크 기능
@bot.command(name='출석', help='출석 체크를 합니다. 24시간마다 가능합니다.')
async def attendance(ctx):
    user = ctx.author
    user_id = user.id

    # 현재 시간 (UTC)
    now_utc = datetime.datetime.now(pytz.utc)

    # 한국 시간대 (UTC+9)
    kst = pytz.timezone('Asia/Seoul')

    # 한국 시간대로 변환
    now_kst = now_utc.astimezone(kst)

    # 한국 시간대의 자정
    midnight_kst = datetime.datetime.combine(now_kst.date(), datetime.time(0, 0, 0))
    midnight = kst.localize(midnight_kst)
    
    if user_id in user_last_attendance:
        last_attendance = user_last_attendance[user_id]
        if midnight < last_attendance:
            await ctx.send(f'{user.mention}, 출석 체크는 자정마다 가능합니다.')
            return

    attendance_points = config['출석']
    user_points[user_id] = user_points.get(user_id, 0) + attendance_points
    user_last_attendance[user_id] = now_kst
    save_user_points()
    await ctx.send(f'{user.mention}, 출석 체크 완료! {attendance_points} {word_plus_josa(points_name, ("이", "가"))} 추가되었습니다. 현재 {points_name}: {user_points[user_id]}{points_name}')

# 유저별 입장 시간을 저장하는 딕셔너리
user_join_times = {}

# 보이스 채널에 유저가 입장했을 때 실행될 이벤트
@bot.event
async def on_voice_state_update(member, before, after):
    # 채널에 입장하는 경우
    if before.channel is None and after.channel is not None:
        user_join_times[member.id] = datetime.datetime.now()
        # print(f"{member} has joined {after.channel.name} at {user_join_times[member.id]}")

    # 채널에서 퇴장하는 경우
    elif before.channel is not None and after.channel is None:
        if member.id in user_join_times:
            joined_at = user_join_times.pop(member.id)
            duration = datetime.datetime.now() - joined_at
            duration_seconds = int(duration.total_seconds())
            max_duration = 3600 * config['최대접속시간']
            if duration_seconds >= max_duration:
                duration_seconds = max_duration

            # print(f"{member} has left {before.channel.name} after {duration}")
            points_per_minute = config['분당접속']

            points = math.floor(duration_seconds / 60 * points_per_minute)
            user_points[member.id] = user_points.get(member.id, 0) + points

            save_user_points()
            #서버 이동시 수정 필요
            channel = bot.get_channel(1238368321976664065)
            await channel.send(f'{member.mention}님, 디코 접속으로 인해 {points} {points_name} 획득!')

# @bot.command(name='채널아이디', help='현재 채널의 ID를 출력합니다.')
# async def channel_id(ctx):
#     channel = ctx.channel
#     await ctx.send(f'현재 채널의 ID는 {channel.id} 입니다.')
#endregion points

@bot.command(name='목록', help='현재 열려있는 베팅 목록을 출력합니다.')
async def listbets(ctx):
    if not current_bets:
        await ctx.send('현재 열려있는 베팅이 없습니다.')
        return

    embed = discord.Embed(title="현재 열려있는 베팅 목록", color=discord.Color.blue())
    for match, details in current_bets.items():
        if details['status'] == 'start':
            options = details['options']
            embed.add_field(name=f'매치: {match}', value=f"옵션 1: {options[0]} vs 옵션 2: {options[1]}", inline=False)

    await ctx.send(embed=embed)

# 베팅 시작
@bot.command(name='시작', help='베팅을 시작합니다. 사용법: $시작 [매치] [옵션1] [옵션2]')
async def startbet(ctx, match: str, option1: str, option2: str):
    if not has_required_role(ctx):
        await ctx.send('이 명령어를 실행할 권한이 없습니다.')
        return

    if option1 == option2:
        await ctx.send('동일한 옵션은 불가능합니다.')
        return

    current_bets[match] = {}

    current_bets[match]['options'] = [option1, option2]
    current_bets[match]['bets'] = {option1: {}, option2: {}}
    current_bets[match]['info'] = {option1: {'sum' : 0, 'ratio' : 2}, option2: {'sum' : 0, 'ratio' : 2}}
    current_bets[match]['status'] = 'start'
    betting_active = True

    # 임베드 생성
    embed = discord.Embed(
        title=f"베팅 시작 - {match}",
        description="베팅이 시작되었습니다!",
        color=discord.Color.blue()  # 임베드 색상
    )

    # 옵션 1, 2를 필드로 추가
    embed.add_field(name="옵션 1", value=option1, inline=True)
    embed.add_field(name="옵션 2", value=option2, inline=True)

    # 메시지 보내기
    await ctx.send(embed=embed)

#배당 계산
async def get_ratio_message(match: str, message: str):
    for option in current_bets[match]['options']:
        message += f'옵션 {option}: {current_bets[match]["info"][option]["sum"]} {points_name}, 배당: {current_bets[match]["info"][option]["ratio"]:.2f}\n'

        message += f'   베팅 목록 \n'
        for user_id, points in current_bets[match]['bets'][option].items():
            member = await bot.fetch_user(user_id)
            message += f'       {member.display_name} : {points} {points_name}\n'    

    return message

class PointsConverter(commands.Converter):
    async def convert(self, ctx, argument):
        if argument.lower() == '올인':
            user = ctx.author
            return user_points.get(user.id, 0)
        
        try:
            points = int(argument)
            return points
        except ValueError:
            raise commands.BadArgument(f'{word_plus_josa(points_name, ("은", "는"))} 숫자로 입력해주세요.')

current_bets_sorted_by_user = {}

# 베팅하기
@bot.command(name='베팅', help=f'베팅합니다. 사용법: $베팅 [매치] [옵션] [{config["최소베팅점수"]} <= {points_name} <= {config["최대베팅점수"]}] or 올인')
async def bet(ctx, match: str, option: str, points: PointsConverter):
    user = ctx.author

    if current_bets.get(match, '') == '':
        await ctx.send('해당 베팅이 없습니다.')
        return

    if current_bets[match]['status'] != 'start':
        await ctx.send('베팅이 열려있지 않습니다.')
        return

    if option not in current_bets[match]['options']:
        await ctx.send(f'잘못된 옵션입니다. 사용 가능한 옵션: {current_bets[match]["options"]}')
        return

    option1 = current_bets[match]['options'][0]
    option2 = current_bets[match]['options'][1]

    try:
        # 멤버를 가져오려고 시도
        member = await commands.MemberConverter().convert(ctx, option1)
        if user == member:
            await ctx.send(f'매치 참여자는 베팅에 참가할 수 없습니다.')
            return       
    except commands.MemberNotFound:
        print("")

    try:
        # 멤버를 가져오려고 시도
        member = await commands.MemberConverter().convert(ctx, option2)
        if user == member:
            await ctx.send(f'매치 참여자는 베팅에 참가할 수 없습니다.')
            return       
    except commands.MemberNotFound:
        print("")

    # 유저가 이미 다른 옵션에 베팅했는지 확인
    other_option = option2 if option == option1 else option1
    if user.id in current_bets[match]['bets'][other_option]:
        await ctx.send('이미 다른 옵션에 베팅하셨습니다.')
        return
    
    if points < config['최소베팅점수']:
        await ctx.send(f'최소 {word_plus_josa(points_name, ("은", "는"))} {config["최소베팅점수"]} {points_name}입니다.')
        return
    
    if points > config['최대베팅점수']:
        await ctx.send(f'최대 {word_plus_josa(points_name, ("은", "는"))} {config["최대베팅점수"]} {points_name}입니다.')
        return

    if user_points.get(user.id, 0) < points:
        await ctx.send(f'{word_plus_josa(points_name, ("이", "가"))} 부족합니다.')
        return

    user_points[user.id] -= points
    current_bets[match]['bets'][option][user.id] = current_bets[match]['bets'][option].get(user.id, 0) + points

    if current_bets_sorted_by_user.get(user.id, None) is None:
        current_bets_sorted_by_user[user.id] = {}
    
    if current_bets_sorted_by_user[user.id].get(match, None) is None:
        current_bets_sorted_by_user[user.id][match] = {'option' : option, 'points' : points}
    else:
        current_bets_sorted_by_user[user.id][match]['points'] += points

    #배당 구하기
    current_bets[match]['info'][option]['sum'] = current_bets[match]['info'][option]['sum'] + points
    total_points = current_bets[match]['info'][option1]['sum'] + current_bets[match]['info'][option2]['sum']

    if current_bets[match]['info'][option1]['sum'] > 0:
        current_bets[match]['info'][option1]['ratio'] = total_points / current_bets[match]['info'][option1]['sum']
    else:
        current_bets[match]['info'][option1]['ratio'] = 99
        
    if current_bets[match]['info'][option2]['sum'] > 0:
        current_bets[match]['info'][option2]['ratio'] = total_points / current_bets[match]['info'][option2]['sum']
    else:
        current_bets[match]['info'][option2]['ratio'] = 99

    bet_message = f'{user.mention}님, {points} {word_plus_josa(points_name, ("을", "를"))} {option}에 베팅했습니다. 남은 {points_name}: {user_points[user.id]}{points_name}\n'
    bet_message = await get_ratio_message(match, bet_message)

    save_user_points()
    await ctx.send(bet_message)

# 베팅 종료
@bot.command(name='종료', help='베팅을 종료합니다. 사용법: $종료 [매치]')
async def endbet(ctx, match: str):
    if not has_required_role(ctx):
        await ctx.send('이 명령어를 실행할 권한이 없습니다.')
        return

    if current_bets.get(match, '') == '':
        await ctx.send('해당 베팅이 없습니다.')
        return

    if current_bets[match]['status'] != 'start':
        await ctx.send('베팅이 열려있지 않습니다.')
        return

    current_bets[match]['status'] = 'end'

    endbet_message = '베팅이 종료되었습니다. 경기 종료 후 결과를 발표해주세요.\n'
    endbet_message = await get_ratio_message(match, endbet_message)
    
    await ctx.send(endbet_message)

# 베팅 취소
@bot.command(name='취소', help=f'진행 중인 베팅을 취소하고 {word_plus_josa(points_name, ("을", "를"))} 돌려줍니다. 사용법: $취소 [매치]')
async def cancel_bet(ctx, match: str):
    if not has_required_role(ctx):
        await ctx.send('이 명령어를 실행할 권한이 없습니다.')
        return

    if current_bets.get(match, '') == '':
        await ctx.send('해당 베팅이 없습니다.')
        return
    # 베팅이 열려있거나, 닫혀있을 때 모두 취소가 되어야 함

    # {points_name} 돌려주기
    for option in current_bets[match]['options']:
        for user_id, points in current_bets[match]['bets'][option].items():
            user_points[user_id] = user_points.get(user_id, 0) + points
            current_bets_sorted_by_user[user_id].pop(match)
            member = await bot.fetch_user(user_id)
            await ctx.send(f'{member.mention}님, 베팅 취소로 인해 {points}{points_name}이/가 반환되었습니다. 현재 {points_name}: {user_points[user_id]}{points_name}')

    save_user_points()

    current_bets[match].clear()
    current_bets.pop(match)
    await ctx.send('베팅이 취소되었습니다.')

# 결과 발표
@bot.command(name='결과', help='베팅 결과를 발표합니다. 사용법: $결과 [매치] [승리 옵션]')
async def announce(ctx, match: str, winning_option: str):
    if not has_required_role(ctx):
        await ctx.send('이 명령어를 실행할 권한이 없습니다.')
        return

    if current_bets.get(match, '') == '':
        await ctx.send('해당 베팅이 없습니다.')
        return

    if current_bets[match]['status'] != 'end':
        await ctx.send('베팅이 종료되지 않았습니다.')
        return

    if winning_option not in current_bets[match]['options']:
        await ctx.send(f'잘못된 옵션입니다. 사용 가능한 옵션: {current_bets[match]["options"]}')
        return

    option1 = current_bets[match]['options'][0]
    option2 = current_bets[match]['options'][1]

    if option1 == winning_option:
        losing_option = option2
    else:
        losing_option = option1

    try:
        # 멤버를 가져오려고 시도
        winning_member = await commands.MemberConverter().convert(ctx, winning_option)
        winning_member_id = winning_member.id
    except commands.MemberNotFound:
        winning_member_id = -1

    try:
        # 멤버를 가져오려고 시도
        losing_member = await commands.MemberConverter().convert(ctx, losing_option)
        losing_member_id = losing_member.id
    except commands.MemberNotFound:
        losing_member_id = -1

    winning_bets = current_bets[match]['bets'][winning_option]
    losing_bets = current_bets[match]['bets'][losing_option]
    total_winning_points = sum(winning_bets.values())
    total_losing_points = sum(losing_bets.values())

    total_points = total_winning_points + total_losing_points

    if winning_member_id != -1:
        add_points = math.floor(config['승리자점수비율'] / 100 * (total_winning_points + total_losing_points)) + config['승리자기본점수']
        user_points[winning_member_id] = user_points.get(winning_member_id, 0) + add_points
        total_points -= math.floor(config['승리자점수비율'] / 100 * (total_winning_points + total_losing_points))
        member = await bot.fetch_user(winning_member_id)
        await ctx.send(f'{member.mention}님, 승리하여 {add_points} {word_plus_josa(points_name, ("을", "를"))} 획득하셨습니다! 현재 {points_name}: {user_points[winning_member_id]}{points_name}')

    if losing_member_id != -1:
        add_points = math.floor(config['패배자점수비율'] / 100 * (total_winning_points + total_losing_points)) + config['패배자기본점수']
        user_points[losing_member_id] = user_points.get(losing_member_id, 0) + add_points
        total_points -= math.floor(config['패배자점수비율'] / 100 * (total_winning_points + total_losing_points))
        member = await bot.fetch_user(losing_member_id)
        await ctx.send(f'{member.mention}님, 패배하여 {add_points} {word_plus_josa(points_name, ("을", "를"))} 획득하셨습니다! 현재 {points_name}: {user_points[losing_member_id]}{points_name}')
    
    if total_winning_points == 0:
        await ctx.send('승리한 옵션에 베팅한 사람이 없습니다.')
    else:
        ratio = total_points / total_winning_points
        for user_id, points in winning_bets.items():
            reward = points * ratio
            user_points[user_id] = user_points.get(user_id, 0) + math.floor(reward)
            member = await bot.fetch_user(user_id)
            await ctx.send(f'{member.mention}님, {points}{word_plus_josa(points_name, ("을", "를"))} 베팅하여 {reward:.0f}{word_plus_josa(points_name, ("을", "를"))} 획득하셨습니다! 현재 {points_name}: {user_points[user_id]}{points_name}')

    await ctx.send(f'베팅 결과 발표! 승리한 옵션: {winning_option}, 배당은 {ratio:.2f}배였습니다.')

    for user_id in winning_bets:
        current_bets_sorted_by_user[user_id].pop(match)
    for user_id in losing_bets:
        current_bets_sorted_by_user[user_id].pop(match)

    save_user_points()
    current_bets[match].clear()
    current_bets.pop(match)

# 현재 베팅 상태 확인
@bot.command(name='배당', help='현재 진행 중인 베팅의 상태를 확인합니다. $배당 [매치]')
async def betstatus(ctx, match: str):
    if current_bets.get(match, '') == '':
        await ctx.send('해당 베팅이 없습니다.')
        return
    
    status_message = '현재 베팅 상태\n'
    status_message = await get_ratio_message(match, status_message)
    
    await ctx.send(status_message)

@bot.command(name='랭킹', help=f'{points_name} 기준, 랭킹을 출력합니다.')
async def print_leaderboard(ctx):
    global first_user
    role = discord.utils.get(ctx.guild.roles, name="스잘알")
    prev_first_user = ctx.guild.get_member(first_user)
    if prev_first_user != None:
        await prev_first_user.remove_roles(role)
            
    # 임베드 생성
    embed = discord.Embed(
        title=f"랭킹",
        description="스잘알에 등극하세요!",
        color=discord.Color.blue()  # 임베드 색상
    )

    sorted_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)
    for idx, (user_id, points) in enumerate(sorted_users, start=1):
        member = await bot.fetch_user(user_id)

        idx_str = f'{idx}'
        if idx == 1:
            user = ctx.guild.get_member(user_id)
            first_user = user_id
            idx_str = f'{idx} - 스잘알'
            await user.add_roles(role)

        embed.add_field(name = f'{idx_str}', value=f'{member.display_name} : {points:,} {points_name}', inline=False)
        
        if (idx == 20):
            break
        
    save_first_user()
    await ctx.send(embed=embed)

@bot.command(name='랭킹더보기리그', help=f'{points_name} 기준, 랭킹을 출력합니다.')
async def print_leaderboard_extra(ctx):
    global first_user
    role = discord.utils.get(ctx.guild.roles, name="스잘알")
    prev_first_user = ctx.guild.get_member(first_user)
    if prev_first_user != None:
        await prev_first_user.remove_roles(role)
            
    sorted_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)
    leaderboard_message = "랭킹:\n"
    for idx, (user_id, points) in enumerate(sorted_users, start=1):
        member = await bot.fetch_user(user_id)
        leaderboard_message += f"{idx}. {member.display_name}: {points}{points_name}\n"

        if idx == 1:
            user = ctx.guild.get_member(user_id)
            first_user = user_id
            await user.add_roles(role)
            leaderboard_message += f"축하합니다! {role.name} 칭호가 부여되었습니다!\n"
        
    save_first_user()
    await ctx.send(leaderboard_message)

# 봇 실행
bot.run(TOKEN)