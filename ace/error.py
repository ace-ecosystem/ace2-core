# vim: sw=4:ts=4:et
# utility functions to report errors

import logging
import os
import os.path
import shutil
import smtplib
import sys
import traceback

from datetime import datetime
from email.mime.text import MIMEText
from subprocess import Popen, PIPE

import ace

def report_exception():
    import ace.engine

    _, reported_exception, _ = sys.exc_info()

    # spit it out to stdout first
    if ace.DUMP_TRACEBACKS:
        traceback.print_exc()

    try:
        output_dir = os.path.join(ace.DATA_DIR, ace.CONFIG['global']['error_reporting_dir'])
        #if not os.path.exists(output_dir):
            #try:
                #os.makedirs(output_dir)
            #except Exception as e:
                #logging.error("unable to create directory {}: {}".format(output_dir, str(e)))
                #return

        error_report_path = os.path.join(output_dir, datetime.now().strftime('%Y-%m-%d:%H:%M:%S.%f'))
        with open(error_report_path, 'w') as fp:
            if ace.engine.CURRENT_ENGINE:
                fp.write("CURRENT ENGINE: {}\n".format(ace.engine.CURRENT_ENGINE))
                fp.write("CURRENT ANALYSIS TARGET: {}\n".format(ace.engine.CURRENT_ENGINE.root))
                if ace.engine.CURRENT_ENGINE.root:
                    fp.write("CURRENT ANALYSIS MODE: {}\n".format(ace.engine.CURRENT_ENGINE.root.analysis_mode))

            fp.write("EXCEPTION\n")
            fp.write(str(reported_exception))
            fp.write("\n\nSTACK TRACE\n")
            fp.write(traceback.format_exc())

        return error_report_path

        if ace.engine.CURRENT_ENGINE and ace.engine.CURRENT_ENGINE.root:
            if os.path.isdir(ace.engine.CURRENT_ENGINE.root.storage_dir):
                analysis_dir = '{}.ace'.format(error_report_path)
                try:
                    shutil.copytree(ace.engine.CURRENT_ENGINE.root.storage_dir, analysis_dir)
                    logging.warning("copied analysis from {} to {} for review".format(ace.engine.CURRENT_ENGINE.root.storage_dir, analysis_dir))
                except Exception as e:
                    logging.error("unable to copy from {} to {}: {}".format(ace.engine.CURRENT_ENGINE.root.storage_dir, analysis_dir, e))

        # do we send an email?
        #email_addresses = [x.strip() for x in ace.CONFIG['global']['error_reporting_email'].split(',') if x.strip() != '']
        #if len(email_addresses) > 0:
            #try:
                #email_message = 'From: {0}\r\nTo: {1}\r\nSubject: {2}\r\n\r\n{3}'.format(
                    #ace.CONFIG['smtp']['mail_from'],
                    #', '.join(email_addresses), 
                    #'ACE Exception Reported',
                    #str(reported_exception) + '\n\n' + traceback.format_exc())
                #server = smtplib.SMTP(ace.CONFIG['smtp']['server'])
                #server.sendmail(ace.CONFIG['smtp']['mail_from'], email_addresses, email_message)
                #server.quit()
            #except Exception as e:
                #logging.error("unable to send email: {0}".format(str(e)))

    except Exception as e:
        logging.error("uncaught exception we reporting an exception: {}".format(e))
