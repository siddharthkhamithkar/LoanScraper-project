import json
import os
import pathlib
import sys
from json.decoder import JSONDecodeError
from discord import SyncWebhook
import datefinder
import requests
import pandas as pd
import re
from datetime import datetime
import time
from pymongo import MongoClient
import pytz
import discord
import gspread
import gspread_dataframe as gd
import logging

with open("config.json", "r") as config_file:
    config = json.load(config_file)

client_id = config["client_id"]
secret_id = config["secret_id"]

master_path = pathlib.Path(__file__).parent
gc = gspread.service_account(filename=str(master_path / 'sheets_credentials.json'))
gsheet_url = config["spreadsheet_url"]
sh = gc.open_by_url(gsheet_url)
ws = sh.worksheet('Loans')
logging.basicConfig(level=logging.ERROR, filename='errors.log')
client = discord.Client(intents=discord.Intents.default())


def LoanScraper():
    while True:
        try:
            auth = requests.auth.HTTPBasicAuth(client_id, secret_id)

            data = {"grant_type": "password",
                    "username": config["username"],
                    "password": config["password"]}

            headers = {"User-Agent": "LoanBot/1.00"}

            res = requests.post("https://www.reddit.com/api/v1/access_token", auth=auth, data=data, headers=headers)

            token = res.json()["access_token"]

            headers["Authorization"] = f"bearer {token}"

            res = requests.get("https://oauth.reddit.com/r/Borrow/new", headers=headers)

            df = get_dataframe_from_gsheet()

            for post in res.json()["data"]["children"]:
                df1 = pd.DataFrame({"Username": [post["data"]["author"]], "Return_Amount": [post["data"]["title"]],
                                    "Mode": [post["data"]["title"]], "Time_EST": [post["data"]["created"]],
                                    "Time_PST": [post["data"]["created"]], "Req_Amount": [post["data"]["title"]],
                                    "URL": [post["data"]["url"]], "Loan ID": post["kind"] + "_" + post["data"]["id"],
                                    "Location": "", "Profit": "", "Profit %": "",
                                    "Return Date": [post["data"]["created"]], "ROI Daily": "", "ROI Monthly": "",
                                    "Days": ""
                                       , "Paid_Loans": "", "Total_Borrowed": "", "Total_Owed": ""
                                       , "Inprogress_Loans": "", "SelfText": post["data"]["selftext"]},
                                   index=[0])
                loan_id = post["kind"] + "_" + post["data"]["id"]
                loan_comment_id = str(post["data"]["id"])

                print(df1["Mode"].values[0])

                if not is_post_valid(df=df, df1=df1, loan_id=loan_id, selftext=df1["SelfText"].values[0]):
                    break

                currency = get_currency_from_str(string=df1["Mode"].values[0].lower())
                if not currency:
                    break

                # Get EST time.
                local_time = datetime.fromtimestamp(df1["Time_EST"].values[0], pytz.timezone("US/Eastern"))
                df1["Time_EST"] = df["Time_EST"].astype(str)
                df1["Time_EST"].values[0] = local_time.strftime("%#I:%M %p - %#m/%#d/%#y")

                # Get PST time.
                local_timep = datetime.fromtimestamp(df1["Time_PST"].values[0], pytz.timezone("US/Pacific"))
                df1["Time_PST"] = df["Time_PST"].astype(str)
                df1["Time_PST"].values[0] = local_timep.strftime("%#I:%M %p - %#m/%#d/%#y")

                # Get loan amount.
                amount = get_loan_amount(string=df1["Req_Amount"].values[0].lower())
                if amount:
                    df1["Req_Amount"].values[0] = amount
                else:
                    continue

                df1["Return_Amount"].values[0] = df1["Return_Amount"].values[0].lower().replace(",", "")
                if "repay" or "repaid" or "repayment" in df1["Return_Amount"].values[0].lower():
                    repayment = re.findall(r"\B[$/€/£]\d+", df1["Return_Amount"].values[0].lower())
                    y = list(map(str, repayment))

                    if len(y) > 1:
                        return_amt = y[1]
                        return_amt = return_amt[1:]
                        return_amt = int(return_amt)
                        x = str(return_amt)

                        index = df1["Mode"].values[0].rindex(x)
                        lenth = len(x)
                        returns = 0

                        post_title = df1["Return_Amount"].values[0].lower()
                        total_payments = get_payment_amount(post_title)
                        print(total_payments)

                        repayment = re.findall(r"\B[$/€/£]\d+", post_title)
                        y = list(map(str, repayment))

                        if len(y) > 1:
                            return_amt = y[1]
                            x = return_amt[1:]

                            index = df1["Mode"].values[0].rindex(x)
                            lenth = len(x)
                            returns = 0
                            if total_payments:
                                total_payments = total_payments + 1  # Add one for the loop
                            else:
                                total_payments = len(y)

                        for i in range(total_payments):
                            if i == 0:
                                pass
                            else:
                                return_amt1 = y[i]
                                return_amt1 = return_amt1[1:]
                                return_amt1 = int(return_amt1)
                                returns = returns + return_amt1
                        df1["Return_Amount"].values[0] = returns

                    elif len(y) == 1:
                        df1["Return_Amount"].values[0] = df1["Req_Amount"].values[0]
                        x = str(df1["Req_Amount"].values[0])
                        index = df1["Mode"].values[0].rindex(x)
                        lenth = len(x)
                    else:
                        print("CurrencyError: Currency has been inserted incorrectly")
                        time.sleep(20)
                        break
                else:
                    break

                strimmed = df1["Mode"].values[0][index + lenth:]
                v = datetime.now()

                matches = datefinder.find_dates(strimmed)
                for match in matches:
                    v = match

                dformat = "%m/%d/%y"

                df1["Return Date"] = df["Return Date"].astype(str)
                df1["Return Date"].values[0] = local_timep.strftime("%m/%d/%y")
                dtime = datetime.strptime(df1["Return Date"].values[0], dformat)

                print(v)

                if "USA" or "US" or "U.S" or "U.S.A" in df1["Location"].values[0]:
                    v = v.strftime("%m/%d/%y")
                elif any(country in df1["Location"].values[0] for country in ["China", "Japan", "Korea", "Iran"]):
                    v = v.strftime("%y/%m/%d")
                else:
                    v = v.strftime("%d/%m/%y")

                print(v)

                v = datetime.strptime(v, dformat)

                print(v)

                roi = v - dtime
                days = roi.days
                days = days - 1

                if days <= 0:
                    days = 1

                # Get number of days
                df1["Days"].values[0] = days

                # Get return date.
                df1["Return Date"].values[0] = v
                df1["Return Date"].values[0] = df1["Return Date"].values[0].strftime("%#m/%#d/%#y")

                # Calculate profit.
                df1["Profit"].values[0] = int(df1["Return_Amount"].values[0]) - df1["Req_Amount"].values[0]
                df1["Profit %"].values[0] = ((df1["Profit"].values[0] / df1["Req_Amount"].values[0]) * 100)
                df1["Profit %"].values[0] = number_formatting(df1["Profit %"].values[0])

                # Get location.
                location = re.search(r"\B[#].+?[)]", post["data"]["title"])
                location = location.group()
                location = location[1:len(location) - 1]
                df1["Location"].values[0] = location

                df1["Mode"].values[0] = get_payment_methods(string=df1['Mode'].values[0].lower())

                # Calculate ROI.
                df1["ROI Daily"].values[0] = (((df1["Return_Amount"].values[0] - df1["Req_Amount"].values[0]) /
                                               df1["Req_Amount"].values[0]) * 100) / days
                df1["ROI Daily"].values[0] = number_formatting(df1["ROI Daily"].values[0])

                df1["ROI Monthly"].values[0] = (float(df1["ROI Daily"].values[0]) * 30)
                df1["ROI Monthly"].values[0] = number_formatting(df1["ROI Monthly"].values[0])

                college_test_server_channel = "https://discord.com/api/webhooks/1134450758729871421/jtU5_J1Ig2n_0PpQtUniWe17giJtbz6RCl8ivri7ZCjsR2AOm1Azms43w263Non3BPVs"

                discord_url = college_test_server_channel

                sending_id = send_discord_message(df1=df1,
                                                  post_title=post["data"]["title"],
                                                  post_url=post["data"]["url"],
                                                  currency=currency, discord_url=discord_url)

                print("NEW POST")

                counter = 0
                comments_extracted = parse_comment(loan_comment_id, headers, counter)

                df1["Paid_Loans"].values[0] = number_formatting(comments_extracted[0])
                df1["Paid_Loans"].values[0] = str(df1["Paid_Loans"].values[0])
                df1["Total_Borrowed"].values[0] = number_formatting(comments_extracted[1])
                df1["Total_Borrowed"].values[0] = str(df1["Total_Borrowed"].values[0])
                df1["Total_Owed"].values[0] = number_formatting(comments_extracted[2])
                df1["Total_Owed"].values[0] = str(df1["Total_Owed"].values[0])
                df1["Inprogress_Loans"].values[0] = number_formatting(comments_extracted[3])
                df1["Inprogress_Loans"].values[0] = str(df1["Inprogress_Loans"].values[0])

                send_edited_discord_message(df1=df1,
                                            post_title=post["data"]["title"],
                                            post_url=post["data"]["url"],
                                            currency=currency, discord_url=discord_url, sending_id=sending_id)

                # Merge old posts with new posts.
                df = pd.concat([df, df1], ignore_index=True)

                # print(df1)
                # df1_dict = df1.to_dict(orient='records')
                # df1_dict_actual = df1_dict[0]
                # print(df1_dict_actual)
                save_to_google_sheets(df)

                pushToDB(df1)

            time.sleep(5)

        except JSONDecodeError as e:
            print("JSON Decode Error: JSON file is not being refreshed properly")
            logging.error(e, exc_info=True)
            check_log_size('errors.log')
            time.sleep(120)

        except TypeError as e:
            print("Type Error: Some calculation isn't taking place")
            logging.error(e, exc_info=True)
            check_log_size('errors.log')
            time.sleep(120)

        except KeyError as e:
            print("Key Error: Something doesn't match between the file and codes")
            logging.error(e, exc_info=True)
            check_log_size('errors.log')
            time.sleep(120)

        except ValueError as e:
            print("Value Error: Invalid Date Format")
            logging.error(e, exc_info=True)
            check_log_size('errors.log')
            time.sleep(120)

        except UnboundLocalError as e:
            print("Still figuring this one out")
            logging.error(e, exc_info=True)
            check_log_size('errors.log')
            time.sleep(120)

        except AttributeError as e:
            print("Attribute Error: Post has been made in incorrect format")
            logging.error(e, exc_info=True)
            check_log_size('errors.log')
            time.sleep(120)

        except gspread.exceptions.APIError as e:
            print("Google API Error: Google server side error")
            logging.error(e, exc_info=True)
            check_log_size('errors.log')
            time.sleep(120)

        except RecursionError as e:
            print("Recursion Error: Too many calls made")
            logging.error(e, exc_info=True)
            check_log_size('errors.log')
            time.sleep(120)

        except requests.exceptions.ConnectionError as e:
            print("ConnectionError: Too many Reddit Api Requests")
            logging.error(e, exc_info=True)
            check_log_size('errors.log')
            time.sleep(120)


def get_payment_amount(post_title) -> int:
    pattern = r'\((.*?)\)'
    matches = re.findall(pattern, post_title)

    for line in matches:
        possible_dates = line.split(' ')
        dates_amount = len([x for x in map(lambda x: list(datefinder.find_dates(x)), possible_dates) if x])
        payments_amount = len(re.findall(r'\$\d+', line))

        # Make sure we only check this for lines where there is a payment amount and a date.
        if payments_amount and dates_amount:
            # If the dates and prices are not the same, there has been a typing error.
            if dates_amount != payments_amount:
                # There might be an extra date or an extra payment amount. Choose the lower one.
                return min([dates_amount, payments_amount])


def get_payment_methods(string: str) -> str:
    mode = []
    if "paypal" in string:
        mode.append(" PayPal ")
    if "cashapp" in string:
        mode.append(" CashApp ")
    if "venmo" in string:
        mode.append(" Venmo ")
    if "zelle" in string:
        mode.append(" Zelle ")
    if "apple" in string:
        mode.append("ApplePay")

    if len(mode) == 0:
        mode.append(" Unknown ")

    modes = "/".join(map(str, mode))

    return modes


def get_currency_from_str(string) -> str:
    currencies = ["$", "€", "£"]

    for currency in currencies:
        if currency in string:
            return currency

    print_dot(times=5)


def loan_exists_in_mongodb(loan_id):
    count = coll.count_documents({"Loan ID": loan_id})
    return count > 0


def is_post_valid(df, df1, loan_id, selftext) -> bool:
    if loan_exists_in_mongodb(loan_id):
        print(f"Loan {loan_id} already exists in MongoDB. Skipping...")
        return False

    if (df["Loan ID"].eq(loan_id)).any():
        print_dot(times=4)
        return False

    # Check if post is NOT a loan request.
    if "req" not in df1["Req_Amount"].values[0].lower():
        print_dot(times=3)
        return False

    if "arranged" in df1["Req_Amount"].values[0].lower():
        print_dot(times=5)
        return False

    if "arranged" in selftext:
        print_dot(times=5)
        return False

    return True


def get_loan_amount(string) -> int:
    if "req" in string:
        dump = string.replace(",", "")
        match = re.search(r"\d+", dump)
        if match:
            matched_value = match.group()
            return int(matched_value)


def print_dot(times=5):
    for _ in range(0, times):
        print(". ", end="")
        time.sleep(1)
    print("")


def number_formatting(n):
    if n == 0:
        return '0'
    elif n == int(n):
        return '{:.0f}'.format(n)
    else:
        return '{:.2f}'.format(n)


def send_discord_message(df1, post_title, post_url, currency, discord_url):
    redditor_profile_url = f"https://www.reddit.com/user/{df1['Username'].values[0]}"
    webhook = SyncWebhook.from_url(discord_url)

    embed = discord.Embed(description=post_title)
    embed.set_author(name=df1["Username"].values[0], url=redditor_profile_url)
    embed.add_field(name="REQ Amount", value=currency + str(df1["Req_Amount"].values[0]), inline=True)
    embed.add_field(name="Return Amount", value=currency + str(df1["Return_Amount"].values[0]), inline=True)
    embed.add_field(name="\u200B", value="\u200B")
    embed.add_field(name="Profit", value=currency + str(df1["Profit"].values[0]), inline=True)
    embed.add_field(name="ROI\n", value=str(df1["Profit %"].values[0]) + "%\n", inline=True)
    embed.add_field(name="\u200B", value="\u200B")
    embed.add_field(name="Payment Method\n", value=df1["Mode"].values[0] + "\n")
    embed.add_field(name="\u200B", value="\u200B")
    embed.add_field(name="\u200B", value="\u200B")
    embed.add_field(name="Daily ROI %", value=str(df1["ROI Daily"].values[0]) + "%", inline=True)
    embed.add_field(name="Monthly ROI %", value=str(df1["ROI Monthly"].values[0]) + "%", inline=True)
    embed.add_field(name="\u200B", value="\u200B")
    embed.add_field(name="Time EST", value=df1["Time_EST"].values[0], inline=True)
    embed.add_field(name="Time PST", value=df1["Time_PST"].values[0], inline=True)
    embed.add_field(name="\u200B", value="\u200B")
    embed.add_field(name="Return Date", value=df1["Return Date"].values[0], inline=True)
    embed.add_field(name="Days", value=str(df1["Days"].values[0]), inline=True)
    embed.add_field(name="\u200B", value="\u200B")
    embed.add_field(name="Location\n", value=df1["Location"].values[0] + "\n", inline=False)
    embed.add_field(name="Post Link", value=post_url, inline=False)
    embed.set_thumbnail(
        url="https://styles.redditmedia.com/t5_33lr0/styles/communityIcon_ibpbtkoanvh01.png?width=256&s=be19b3a03070dbfcc68cb1fcf7022d24102ad3a6")

    sending = webhook.send(embed=embed, wait=True)
    sending_id = sending.id
    return sending_id


def get_author_and_comment_body(loan_comment_id, headers):
    submission = requests.get(
        "https://oauth.reddit.com/r/borrow/comments/" + loan_comment_id,
        headers=headers).json()

    comments = submission[1]['data']['children']

    for comment in comments:
        df_comment = pd.DataFrame({"LoansBot": comment["data"]["author"],
                                   "name": comment["data"]["body"],
                                   "kind": comment["kind"]},
                                  index=[0])

        bot = df_comment[df_comment["LoansBot"].str.contains("LoansBot")]
        comment_body = list(bot["name"])

        if not comment_body:
            continue

        return comment['data']['author'], comment_body[0]

    # If we reach this point, there is still no comment by the LoansBot.
    return None, None


def parse_text(comment_body: str):
    paid_loans, unpaid_loans, in_progress_loans, total_owed, outstanding_loans, total_repaid = 0, 0, 0, 0, 0, 0
    for line in comment_body.splitlines():
        if 'loans paid as a borrower' in line or 'loan paid as a borrower' in line:
            paid_loans = re.search(r'has (\d+) loan?s', line)
            paid_loans = 0 if not paid_loans else int(paid_loans.group(1))

            total_repaid = re.search(r'a total of \$(.+)', line)
            total_repaid = 0 if not total_repaid else float(total_repaid.group(1))

        elif 'has not received any loans which are currently marked unpaid' in line:
            unpaid_loans = 0

        elif 'does not have any outstanding loans as a borrower' in line:
            outstanding_loans = 0

        elif 'In-progress loans with' in line:
            # extract number of loans
            in_progress_loans = int(re.search(r'\((\d+) loan.?', line).group(1))

            # extract total amount of money due
            total_owed = float(re.search(r'\$([\d.]+)', line).group(1))

    return paid_loans, total_repaid, total_owed, in_progress_loans


def parse_table(author: str, comment_body: str):
    loans = comment_body.splitlines()[6:]

    paid_loans, total_repaid, unpaid_loans, in_progress_loans, total_owed, outstanding_loans = 0, 0, 0, 0, 0, 0

    for loan in loans:
        try:
            lender, _, amount_borrowed, amount_repaid, unpaid, *_ = loan.split('|')
        except ValueError:
            # Empty table.
            break

        # Ignore borrower lends.
        if lender == author:
            continue
        else:
            total_repaid += float(amount_repaid.split(' ')[0])

            if amount_borrowed == amount_repaid:
                paid_loans += 1

            if amount_borrowed != amount_repaid and not unpaid:
                in_progress_loans += 1

            if unpaid == '***UNPAID***':
                unpaid_loans += 1

            amount_borrowed = float(amount_borrowed.split()[0])
            amount_repaid = float(amount_repaid.split()[0])

            total_owed += amount_borrowed - amount_repaid

    return paid_loans, total_repaid, unpaid_loans, in_progress_loans, total_owed, outstanding_loans


def parse_no_comment():
    paid_loans, total_borrowed, total_owed, in_progress_loans = 0, 0, 0, 0
    print("No Comment Made by LoansBot")
    return paid_loans, total_borrowed, total_owed, in_progress_loans


def parse_comment(loan_comment_id, headers, counter):
    author, comment_body = get_author_and_comment_body(loan_comment_id, headers)
    if not author:
        print("Still no comment by loansbot. Waiting 10 seconds...")
        time.sleep(10)
        counter += 1

        if counter <= 20:
            return parse_comment(loan_comment_id, headers, counter)
        else:
            return parse_no_comment()

    if 'paid as a borrower' not in comment_body:
        paid_loans, total_borrowed, unpaid_loans, total_owed, in_progress_loans, outstanding_loans = parse_table(author,
                                                                                                                 comment_body)
    else:
        paid_loans, total_borrowed, total_owed, in_progress_loans = parse_text(comment_body)

    print(paid_loans, total_borrowed, total_owed, in_progress_loans)
    comments_parsed = [paid_loans, total_borrowed, total_owed, in_progress_loans]
    return comments_parsed


def send_edited_discord_message(df1, post_title, post_url, currency, discord_url, sending_id):
    redditor_profile_url = f"https://www.reddit.com/user/{df1['Username'].values[0]}"
    webhook = SyncWebhook.from_url(discord_url)

    edit = discord.Embed(description=post_title)
    edit.set_author(name=df1["Username"].values[0], url=redditor_profile_url)
    edit.add_field(name="REQ Amount", value=currency + str(df1["Req_Amount"].values[0]), inline=True)
    edit.add_field(name="Return Amount", value=currency + str(df1["Return_Amount"].values[0]), inline=True)
    edit.add_field(name="Past Loans - " + df1["Paid_Loans"].values[0], value="$" + df1["Total_Borrowed"].values[0])
    edit.add_field(name="Profit", value=currency + str(df1["Profit"].values[0]), inline=True)
    edit.add_field(name="ROI\n", value=str(df1["Profit %"].values[0]) + "%\n", inline=True)
    edit.add_field(name="Ongoing Loans - " + df1["Inprogress_Loans"].values[0], value="$" + df1["Total_Owed"].values[0])
    edit.add_field(name="Payment Method\n", value=df1["Mode"].values[0] + "\n")
    edit.add_field(name="\u200B", value="\u200B")
    edit.add_field(name="\u200B", value="\u200B")
    edit.add_field(name="Daily ROI %", value=str(df1["ROI Daily"].values[0]) + "%", inline=True)
    edit.add_field(name="Monthly ROI %", value=str(df1["ROI Monthly"].values[0]) + "%", inline=True)
    edit.add_field(name="\u200B", value="\u200B", inline=True)
    edit.add_field(name="Time EST", value=df1["Time_EST"].values[0], inline=True)
    edit.add_field(name="Time PST", value=df1["Time_PST"].values[0], inline=True)
    edit.add_field(name="\u200B", value="\u200B")
    edit.add_field(name="Return Date", value=df1["Return Date"].values[0], inline=True)
    edit.add_field(name="Days", value=df1["Days"].values[0], inline=True)
    edit.add_field(name="\u200B", value="\u200B")
    edit.add_field(name="Location\n", value=df1["Location"].values[0] + "\n", inline=False)
    edit.add_field(name="Post Link", value=post_url, inline=False)
    edit.set_thumbnail(
        url="https://styles.redditmedia.com/t5_33lr0/styles/communityIcon_ibpbtkoanvh01.png?width=256&s=be19b3a03070dbfcc68cb1fcf7022d24102ad3a6")

    webhook.edit_message(sending_id, embed=edit)


def get_dataframe_from_gsheet():
    df = gd.get_as_dataframe(ws, use_cols=[0, 10])
    # Make sure items in dataframe are not null.
    df = df[df['Username'].notna()]
    df = df.iloc[-10:]
    return df


def save_to_google_sheets(df):
    gd.set_with_dataframe(worksheet=ws, dataframe=df)
    # df = df.tail(1)
    # new_entry = df.values.tolist()
    # gd.append_rows(new_entry)


if len(sys.argv) == 1:
    print("Starting LoanScraper")
    print_dot(times=3)


def check_log_size(log_file):
    # check the file size and clear it if it exceeds 1MB
    if os.path.getsize(log_file) > 1000000:
        open(log_file, 'w').close()


def pushToDB(df):
    try:
        json_str = df.to_json(orient='records')
        json_obj = json.loads(json_str)
        for record in json_obj:
            print(record)
            res = coll.insert_one(record)
            print("Inserted ID:", res.inserted_id)
    except Exception as e:
        print(e)


try:
    uri = config["mongo-uri"]
    mongo_client = MongoClient(uri)
    dbname = mongo_client['loanscraper_posts_actual']
    coll = dbname['posts']
except Exception as e:
    logging.error(e, exc_info=True)
    check_log_size('errors.log')
    time.sleep(120)
    print("Something went wrong. Check logs for further details.")

LoanScraper()
mongo_client.close()
