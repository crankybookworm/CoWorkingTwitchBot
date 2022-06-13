# bot.py
# bot.commands
# Developers - twitch.tv/00mb1, twitch.tv/CrankyBookworm

import os  # for importing env vars for the bot to use
from twitchio.abcs import Messageable
from twitchio import Message, Channel
from twitchio.ext import commands
from twitchio.ext.commands import Bot
from pomo_logic import Pomo, Timer, Task
import datetime
from typing import Dict
from keep_alive import keep_alive
import asyncio
import re
import botDatabase
import json
import logging

################ Setup Section Started ################
logging.basicConfig(filename='bot.log', level=logging.ERROR)

pomo: Pomo = Pomo()
pomoTasks: Dict[str, Dict[str, Task]] = dict()


class CoWorkingBot(Bot):
    def __init__(self):
        # Initialise our Bot with our access token, prefix and a list of channels to join on boot...
        self.allChannels: list = [
            channel.lower() for channel in botDatabase.getChannels()
        ]
        if (len(self.allChannels) == 0):
            self.allChannels.append(os.environ['BOT_NAME'].lower())
        super().__init__(
            token=os.environ['AUTH_TOKEN'],
            prefix="!",
            initial_channels=self.allChannels,
        )
        global pomo
        self.pomo: Pomo = pomo
        self.flipDict = json.load(open('./templates/flipDict.json'))
        self.tasks: Dict[str, Dict[str, Task]] = pomoTasks
        self.asyncTasks: Dict[str, Dict[str, asyncio.Task]] = dict()

    async def event_ready(self):
        # We are logged in and ready to chat and use commands...
        print(f'Logged in as | {self.nick}')
        print(f'User id is | {self.user_id}')
        if not (self.nick in [chan.name for chan in self.connected_channels]):
            self.allChannels.append(self.nick)
            await self.join_channels[self.nick]
        for channel in self.connected_channels:
            self.asyncTasks[channel.name] = dict()
            self.tasks[channel.name] = dict()
            if (botDatabase.outputToFile):
                botDatabase.updateAllTimers(channel.name, [])
            else:
                await self.restoreOldTimers(channel)
            await channel.send(f"/me has landed!")

    async def event_message(self, ctx: Message):
        'Runs every time a message is sent in chat.'
        # make sure the bot ignores itself and the streamer
        if (ctx.echo or not (ctx.channel.name in self.allChannels)
                or ctx.author.name.lower() == self.nick.lower()):
            return
        cmd = ctx.content.split(' ', 1)[0].lower()
        if (cmd.startswith(self._prefix)):
            cmd = cmd[1:]
            if (cmd in list(bot.commands.keys())):
                await bot.handle_commands(ctx)
        else:  # If user has a Timer Running
            timer = self.pomo.get_timer(ctx.channel.name, ctx.author.name)
            if (not (timer is None) and timer.study_mode and not (timer.paused)
                    and not (timer.chat_mode)):
                time = timer.iterEndTime - datetime.datetime.now()
                timeLeft = round(time.total_seconds() / 60)
                await ctx.channel.send(
                    f"{ctx.author.name}, stay focussed! Only {timeLeft} minutes left. You got this!"
                )
################ Setup Section Ended ################

    @commands.command(name="hello")
    async def hello(self, ctx: commands.Context):
        # Send a hello back!
        await ctx.reply(f'Hello {ctx.author.name}!')

################ Pomo Section Started ################
# Pomodoro

    @commands.command(name='pomo')
    async def studyTime(self,
                        ctx: commands.Context,
                        studyPeriod='',
                        breakPeriod='',
                        iterations='',
                        work=''):
        user = ctx.author.name.lower()
        channel = ctx.channel.name.lower()
        prefix = '^' + self._prefix + ctx.command.name
        dRe = " (\\d*\\.|)\\d+"

        # !pomo complete
        if (studyPeriod.lower() == "complete"):
            if self.pomo.cancel_timer(channel, user):
                await ctx.reply(
                    f"Your pomodoro sessions have finished, well done on all your hard work!"
                )
                self.asyncTasks[channel][user].cancel()
                botDatabase.removeTimer(channel, user)
            else:
                await ctx.reply(f"You currently have no active pomo")
            return

        # !pomo chat
        elif (studyPeriod.lower() == "chat"):
            timer = self.pomo.get_timer(channel, user)
            if (timer is None):
                await ctx.reply(f"You currently have no active pomo.")
                return
            timer.triggerChatMode(True)
            botDatabase.writeTimer(channel, timer)
            await ctx.reply(f"Chat mode is on!")
            return

        # !pomo focus
        elif (studyPeriod.lower() == "focus"):
            timer = self.pomo.get_timer(channel, user)
            if (timer is None):
                await ctx.reply(f"You currently have no active pomo.")
                return
            timer.triggerChatMode(False)
            botDatabase.writeTimer(channel, timer)
            await ctx.reply(f"Chat mode is off!")
            return

        # !pomo +/-time
        elif (bool(re.match("^(\\+|\\-)" + dRe[1:] + "( .*)?$", studyPeriod))):
            timer = self.pomo.get_timer(channel, user)
            if (timer is None):
                await ctx.reply(f"You currently have no active pomo.")
                return

            self.asyncTasks[channel][user].cancel()
            self.asyncTasks[channel][user] = asyncio.create_task(self.nextIter(
                ctx, timer, float(studyPeriod)),
                                                                 name=user)
            return

        # !pomo check
        elif (studyPeriod.lower() == "check"):
            if (user in self.tasks[channel].keys()
                    and self.tasks[channel][user].done == False):
                await self.addTask(ctx)
            else:
                await self.timer(ctx)
            return

        elif (
            ((not (self.pomo.get_timer(channel, user) is None)) or
             (user in self.tasks[channel].keys()
              and self.tasks[ctx.channel.name][ctx.author.name].done == False))
                and
            (bool(re.match(prefix + dRe + "( .*)?$", ctx.message.content)))):
            if (user in self.tasks[channel].keys()):
                await self.addTask(ctx)
            else:
                await self.timer(ctx)
            return

        # !pomo pause [Pause Period]
        elif (studyPeriod.lower() == "pause"):
            if (not (bool(re.match(dRe[1:] + "$", breakPeriod)) and
                     float(breakPeriod) <= 300 and float(breakPeriod) >= 5)):
                await ctx.reply(
                    f"To use pause funtion please make sure to follow this format '!pomo pause <pause period>' where the <pause period> is ≥5 and ≤300."
                )
                return
            timer = self.pomo.get_timer(channel, user)
            if (timer is None):
                await ctx.reply(f"You currently have no active pomo.")
                return
            self.asyncTasks[channel][user].cancel()
            timer.pause(float(breakPeriod))
            botDatabase.writeTimer(channel, timer)
            await ctx.reply(f"Pausing timer for {int(breakPeriod)}")
            self.asyncTasks[channel][user] = asyncio.create_task(
                self.restoreWait(ctx, timer), name=user)
            return

        # !pomo resume
        elif (studyPeriod.lower() == "resume"):
            timer: Timer = self.pomo.get_timer(channel, user)
            if (timer is None):
                await ctx.reply(f"You currently have no active pomo.")
                return
            if (not (timer.paused)):
                await ctx.reply(f"You currently have no paused pomo.")
                return
            self.asyncTasks[channel][user].cancel()
            timer.resume()
            botDatabase.writeTimer(channel, timer)
            taskWork = timer.work if len(
                timer.work) <= 50 else timer.work[0:50] + '…'
            await ctx.reply(
                f"Resuming pomo '{taskWork}'. You have {round(timer.timeLeft.total_seconds()/60)} minute(s) left"
            )
            self.asyncTasks[channel][user] = asyncio.create_task(
                self.restoreWait(ctx, timer), name=user)
            return

        # !pomo [Study Period] [Break Period] [Sessions] [Work]
        elif bool(re.match(prefix + dRe * 3 + "( .*)?$", ctx.message.content)):
            studyPeriod = float(studyPeriod)
            breakPeriod = float(breakPeriod)
            iterations = int(iterations)

            try:
                work = ctx.message.content.split(' ', 4)[4]
            except IndexError:
                work = "Work"

            # Validate Time Periods
            if (studyPeriod < 5 or studyPeriod > 300):
                await ctx.reply(
                    f"You can't work for that amount of time, please choose a time between 5 and 300 minutes."
                )
                return
            elif (breakPeriod < 5 or breakPeriod > 300):
                await ctx.reply(
                    f"You can't break for that amount of time, please choose a time between 5 and 300 minutes."
                )
                return
            elif (iterations < 1 or iterations > 10):
                await ctx.reply(
                    f"You can't work for many iterations, please choose between 1 and 10."
                )
                return

        # !pomo [Study Period] [Break Period] [Work]
        elif bool(re.match(prefix + dRe * 2 + "( .*)?$", ctx.message.content)):
            studyPeriod = float(studyPeriod)
            breakPeriod = float(breakPeriod)
            iterations = 1

            try:
                work = ctx.message.content.split(' ', 3)[3]
            except IndexError:
                work = "Work"

            # Validate Time Periods
            if (studyPeriod < 5 or studyPeriod > 300):
                await ctx.reply(
                    f"You can't work for that amount of time, please choose a time between 5 and 300 minutes."
                )
                return
            elif (breakPeriod < 5 or breakPeriod > 300):
                await ctx.reply(
                    f"You can't break for that amount of time, please choose a time between 5 and 300 minutes."
                )
                return

        # !pomo [Study Period] [Work]
        elif bool(re.match(prefix + dRe + "( .*)?$", ctx.message.content)):
            studyPeriod = float(studyPeriod)
            breakPeriod = 0
            iterations = 1

            try:
                work = ctx.message.content.split(' ', 2)[2]
            except IndexError:
                work = "Work"

            # Validate Time Periods
            if (studyPeriod < 5 or studyPeriod > 300):
                await ctx.reply(
                    f"You can't work for that amount of time, please choose a time between 5 and 300 minutes."
                )
                return

        # !pomo help
        else:
            await ctx.reply(
                f"Want to start your own work pomo and appear on stream? Type '!pomo [number]' to set a single pomo. Use '!pomo complete' to cancel it. See the About section for more useful features!"
            )
            return

        timer = self.pomo.set_timer(
            channel=channel,
            user=user,
            userDisplayName=ctx.author.display_name,
            studyPeriod=studyPeriod,
            breakPeriod=breakPeriod,
            iterations=iterations,
            work=work,
            chat_mode=ctx.author.is_mod,
        )
        self.asyncTasks[channel][user] = asyncio.create_task(self.nextIter(
            ctx, timer),
                                                             name=user)

    async def nextIter(self, ctx: Messageable, timer: Timer, modify: int = 0):
        # Regular Pomo Sessions
        if (modify == 0):
            botDatabase.writeTimer(ctx._fetch_channel().name, timer)
            if (timer.study_mode):
                taskWork = timer.work if len(
                    timer.work) <= 50 else timer.work[0:50] + '…'
                if (timer.iterations > 1):
                    await ctx.send(
                        f'{timer.user}, starting work session {timer.currentIteration} of {timer.iterations} on {taskWork} for {round(timer.studyPeriod)} minutes. Good luck!'
                    )
                else:
                    await ctx.send(
                        f"{timer.user}, starting work session on {taskWork} for {round(timer.studyPeriod)} minutes. Good luck!"
                    )
                await asyncio.sleep(timer.studyPeriod * 60)
            if (not (timer.study_mode)):
                if (timer.iterations > 1):
                    await ctx.send(
                        f'{timer.user}, work session {timer.currentIteration} of {timer.iterations} is complete! Enjoy your {round(timer.breakPeriod)} minute break!'
                    )
                else:
                    await ctx.send(
                        f'{timer.user}, work session completed! Enjoy your {round(timer.breakPeriod)} minute break!'
                    )
                await asyncio.sleep(timer.breakPeriod * 60)

        # Modify the Pomo Session and Resume
        elif (modify > 0):
            if (round(timer.timeLeft.total_seconds() / 60) + modify > 300):
                await ctx.reply(
                    f'The session time left should not exceed 300 minutes.')
            else:
                timer.addTime(modify)
                timeLeft = round(timer.timeLeft.total_seconds() / 60)
                await ctx.reply(
                    f'{modify} minutes added to this session. {timeLeft} minute(s) left.'
                )
                botDatabase.writeTimer(ctx._fetch_channel().name, timer)
            await asyncio.sleep(timer.timeLeft.total_seconds())
        else:
            timer.addTime(modify)
            timeLeft = round(timer.timeLeft.total_seconds() / 60)
            await ctx.reply(
                f'{abs(modify)} minutes subtracted from this session. {timeLeft} minute(s) left.'
            )
            if (timeLeft > 0):
                botDatabase.writeTimer(ctx._fetch_channel().name, timer)
                await asyncio.sleep(timer.timeLeft.total_seconds())

        # Iterate to Next Session
        if self.pomo.get_timer(ctx._fetch_channel().name,
                               timer.user) is not None:
            if (timer.nextIter()):
                await self.nextIter(ctx, timer)
            else:
                self.pomo.cancel_timer(ctx._fetch_channel().name, timer.user)
                botDatabase.removeTimer(ctx._fetch_channel().name, timer.user)
                await ctx.send(
                    f'{timer.user}, your pomodoro sessions have finished, well done on all your hard work!'
                )

    async def restoreOldTimers(self, channel: Channel):
        for timerJson in botDatabase.getTimers(channel.name).values():
            try:
                timer: Timer = json.loads(timerJson,
                                          object_hook=lambda d: Timer(**d))
                timeLost = timer.timeLeft
                if (timer.timeLeft.total_seconds() > 0):
                    self.pomo.add_timer(channel.name, timer.user, timer)
                    self.asyncTasks[channel.name][
                        timer.user] = asyncio.create_task(self.restoreWait(
                            channel, timer),
                                                          name=timer.user)
                elif (timer.nextIter()):
                    if (((timeLost + timer.timeLeft).total_seconds()) < 0):
                        iterLeft = True
                        while ((timeLost + timer.timeLeft).total_seconds() <
                               0):
                            timeLost += timer.timeLeft
                            if not (timer.nextIter()):
                                iterLeft = False
                                break
                        if not (iterLeft):
                            botDatabase.removeTimer(channel.name, timer.user)
                            continue
                        else:
                            timer.iterEndTime += timeLost
                    self.pomo.add_timer(channel.name, timer.user, timer)
                    self.asyncTasks[channel.name][
                        timer.user] = asyncio.create_task(self.nextIter(
                            channel, timer),
                                                          name=timer.user)
                else:
                    botDatabase.removeTimer(channel.name, timer.user)
            # except KeyError:
            except TypeError:
                task: Task = json.loads(timerJson,
                                        object_hook=lambda d: Task(**d))
                if (task.done == False):
                    self.tasks[channel.name][task.user] = task
                else:
                    botDatabase.removeTimer(channel.name, task.user)

    async def restoreWait(self, ctx: Channel, timer: Timer):
        await asyncio.sleep(timer.timeLeft.total_seconds())
        if (timer.nextIter()):
            await self.nextIter(ctx, timer)
        else:
            self.pomo.cancel_timer(ctx._fetch_channel().name, timer.user)
            botDatabase.removeTimer(ctx._fetch_channel().name, timer.user)
            await ctx.send(
                f'{timer.user}, your pomodoro sessions have finished, well done on all your hard work!'
            )

    @commands.command(name='timer')
    async def timer(self, ctx: commands.Context):
        if self.pomo.get_timer(ctx.channel.name, ctx.author.name) is not None:
            timeLeft = self.pomo.time_left(ctx.channel.name, ctx.author.name)
            if timeLeft < 1:
                await ctx.reply(
                    f"You have less than 1 minute left on your pomo.")
            elif timeLeft == 1:
                await ctx.reply(f"You have 1 minute left on your pomo.")
            else:
                await ctx.reply(
                    f"You have {timeLeft} minutes left on your pomo.")
        else:
            await ctx.reply(f"You have no current pomo.")

    @commands.command(name="grinders")
    async def grinders(self, ctx: commands.Context):
        timer_array = self.pomo.active_timers[ctx.channel.name.lower()]
        message = f"People studying: "
        for user, timer in timer_array.items():
            if timer.study_mode:
                message += user + " "
        if message == f"People studying: ":
            message = f"Nobody is studying, be the first!"
        await ctx.reply(message)

    @commands.command(name="sleepers")
    async def sleepers(self, ctx: commands.Context):
        timer_array = self.pomo.active_timers[ctx.channel.name.lower()]
        message = f"Taking a break: "
        for user, timer in timer_array.items():
            if not timer.study_mode:
                message += user + " "
        if message == f"Taking a break: ":
            message = f"Nobody is taking a break!"
        await ctx.reply(message)

    @commands.command(name="purgeboard")
    async def purgeBoard(self, ctx: commands.Context):
        if (ctx.author.name == ctx.channel.name):
            self.tasks[ctx.channel.name] = dict()
            for user in self.asyncTasks[ctx.channel.name].keys():
                self.asyncTasks[ctx.channel.name][user].cancel()
            self.asyncTasks[ctx.channel.name] = dict()
            self.pomo.active_timers[ctx.channel.name.lower()] = dict()
            botDatabase.updateAllTimers(ctx.channel.name, [])
            await ctx.reply(f"Purging all tasks and pomos from board!")
        else:
            await ctx.reply(f"Nice Try! Only Streamer can do this.")
################ Pomo Section Ended ################

################ Tasks Section Started ################

    @commands.command(name='task')
    async def addTask(self, ctx: commands.Context, work: str = ''):
        if self.pomo.get_timer(ctx.channel.name, ctx.author.name) is not None:
            timer = self.pomo.get_timer(ctx.channel.name, ctx.author.name)
            taskWork = timer.work if len(
                timer.work) <= 50 else timer.work[0:50] + '…'
            await ctx.reply(
                f"You have a pomo running titled '{taskWork}' with {timer.timeLeft} minutes left."
            )
            return
        elif ctx.author.name in self.tasks[ctx.channel.name].keys(
        ) and self.tasks[ctx.channel.name][ctx.author.name].done == False:
            taskWork = self.tasks[ctx.channel.name][ctx.author.name].work
            taskWork = taskWork if len(
                taskWork) <= 50 else taskWork[0:50] + '…'
            await ctx.reply(f"You have an ongoing task titled '{taskWork}'.")
            return
        elif len(work) == 0:
            await ctx.reply(f"You have no ongoing task.")
            return
        work = ctx.message.content.split(' ', 1)[1]
        task = Task(ctx.author.name, ctx.author.display_name, work)
        self.tasks[ctx.channel.name][ctx.author.name] = task
        botDatabase.writeTimer(ctx.channel.name, task)
        taskWork = task.work if len(task.work) <= 50 else task.work[0:50] + '…'
        await ctx.reply(f"Task '{taskWork}' added.")

    @commands.command(name='done')
    async def rmvTask(self, ctx: commands.Context):
        if self.pomo.get_timer(ctx.channel.name, ctx.author.name) is not None:
            ctx.view.words[1] = 'complete'
            await self.studyTime(ctx)
            return
        if not (ctx.author.name in self.tasks[ctx.channel.name].keys() and
                self.tasks[ctx.channel.name][ctx.author.name].done == False):
            await ctx.reply(f"You have no ongoing task.")
            return
        task: Task = self.tasks[ctx.channel.name][ctx.author.name]
        task.done = True
        self.tasks[ctx.channel.name][ctx.author.name] = task
        botDatabase.writeTimer(ctx.channel.name, task)
        taskWork = task.work if len(task.work) <= 50 else task.work[0:50] + '…'
        await ctx.reply(
            f"You have completed your '{taskWork}' task. It took you {task.timeTakenM} minutes to complete."
        )

    @commands.command(name='finish')
    async def finishTasks(self, ctx: commands.Context, work: str = ''):
        await self.rmvTask(ctx)
        try:
            self.tasks[ctx.channel.name].pop(ctx.author.name)
            botDatabase.removeTimer(ctx.channel.name, ctx.author.name)
        except KeyError:
            pass

    @commands.command(name="rmvtask")
    async def rmvTaskFromBoard(self, ctx: commands.Context, user: str = ''):
        if (ctx.author.is_mod):
            if (len(user) == 0):
                user = ctx.author.name.lower()
            else:
                user = user.lower().replace('@', '')
            timer = self.pomo.get_timer(ctx.channel.name, user)
            if (timer is None):
                if (user in self.tasks[ctx.channel.name].keys()):
                    self.tasks[ctx.channel.name].pop(user)
                    botDatabase.removeTimer(ctx.channel.name, user)
                    await ctx.reply(f"Removed Task found for user '{user}'.")
                else:
                    await ctx.reply(f"No Pomo or Task found for user '{user}'."
                                    )
            else:
                self.asyncTasks[ctx.channel.name].pop(user).cancel()
                botDatabase.removeTimer(ctx.channel.name, user)
                await ctx.reply(f"Removed Task found for user '{user}'.")
        else:
            await ctx.reply(f"Nice Try! Only Mods can do this.")

    @commands.command(name="rmvdone")
    async def rmvDoneTasksFromBoard(self,
                                    ctx: commands.Context,
                                    user: str = ''):
        if (ctx.author.is_mod):
            users = self.tasks[ctx.channel.name].keys()
            for user in users:
                task = self.tasks[ctx.channel.name][user]
                if (task.done == True):
                    self.tasks[ctx.channel.name].pop(user)
                    botDatabase.removeTimer(ctx.channel.name, user)
            await ctx.reply(f"Removed all completed tasks.")
        else:
            await ctx.reply(f"Nice Try! Only Mods can do this.")
################ Tasks Section Ended ################

################ Joining Section Started ################

    @commands.command(name="join")
    async def addCoWorkingStreamer(self,
                                   ctx: commands.Context,
                                   user='',
                                   msg=''):
        if (ctx.channel.name == self.nick):
            if (len(user) == 0):
                user = ctx.author.name.lower()
            else:
                user = user.lower().replace('@', '')
                if (not (user == ctx.author.name.lower()
                         or ctx.author.is_mod)):
                    await ctx.reply(f"You must be a Mod or Joining yourself")
                    return
            if (user in self.allChannels):
                await ctx.reply(f"The bot is already running on this channel.")
                return
            await self.join_channels([user])
            self.asyncTasks[user] = dict()
            self.allChannels.append(user)
            botDatabase.writeTimer(user, None)
            await ctx.reply(
                f"Joined channel {user}. Please visit the website /pomo/{user} to get the browser output. Use '!hello' in {user} channel to test if the bot has arrived."
            )

    @commands.command(name="leave")
    async def removeCoWorkingStreamer(self,
                                      ctx: commands.Context,
                                      user: str = ''):
        if (ctx.channel.name == self.nick):
            if (len(user) == 0):
                user = ctx.author.name.lower()
            else:
                user = user.split(maxsplit=1)[0].lower().replace('@', '')
                if (not (user.lower() == ctx.author.name.lower()
                         or ctx.author.is_mod)):
                    await ctx.reply(f"You must be a Mod or Leaving yourself")
                    return
            if (user in self.allChannels):
                self.allChannels.remove(user)
                botDatabase.removeChannel(user)
                for task in list(self.asyncTasks[user].values()):
                    task.cancel()
                self.asyncTasks.pop(user)
                await ctx.reply(
                    f"The bot will stop running on this channel when it restarts"
                )
            else:
                await ctx.reply(f"The bot is not running on {user} channel")
################ Joining Section Ended ################

################ Fun Commands Section Started ################

    @commands.command(name="flip")
    async def flip(self, ctx: commands.Context, text: str = ''):
        if (len(text) == 0):
            text = ctx.author.display_name
        flippedText = ""
        for chr in text[::-1]:
            if (chr in self.flipDict.keys()):
                flippedText += self.flipDict[chr]
            else:
                flippedText += chr
        await ctx.reply(f"(╯°□°）╯︵{flippedText}")

    @commands.command(name="unflip")
    async def unflip(self, ctx: commands.Context, text: str = ''):
        if (len(text) == 0):
            text = ctx.author.display_name
        await ctx.reply(f"{text}ノ( ゜-゜ノ)")


################ Fun Commands Section Ended ################

#Original Author: https://github.com/00MB/
if __name__ == "__main__":
    if (botDatabase.outputToFile):
        botDatabase.runFileOutputThread(pomo=pomo,
                                        pomoTasks=pomoTasks,
                                        interval=5)
    else:
        keep_alive()
    bot = CoWorkingBot()
    bot.run()
