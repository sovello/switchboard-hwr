import contextlib
import datetime
import optparse
import re

import tablib

from sb.healthworker import models
from django.db import transaction
from django.core.mail import EmailMessage

def fix_phone(phone):
  if phone.startswith('+2557'):
    phone = '07' + phone[5:]
  elif phone.startswith('7'):
    phone = '0' + phone
  return phone

def main():
  parser = optparse.OptionParser()
  parser.add_option('--save', action='store_true', help=u'save changes')
  parser.add_option('--src-email', default="hostmaster@switchboard.org")
  parser.add_option('--dst-email', default="brandon@switchboard.org")
  opts, args = parser.parse_args()

  @contextlib.contextmanager
  def commit_block():
    with transaction.commit_manually():
      if opts.save:
        try:
          yield
          transaction.commit()
        except:
          transaction.rollback()
          raise
      else:
        try:
          yield
          transaction.rollback()
        except:
          transaction.rollback()
          raise

  with commit_block():
    health_workers = models.HealthWorker.objects
    health_workers = health_workers.filter(is_closed_user_group=False)
    health_workers = health_workers.exclude(verification_state=None)
    health_workers = health_workers.exclude(verification_state=models.HealthWorker.UNVERIFIED)
    health_workers = health_workers.exclude(vodacom_phone=None)
    health_workers = health_workers.exclude(vodacom_phone=u'')
    health_workers = health_workers.all()
    health_workers = list(health_workers)
    for h in health_workers:
      if not h.request_closed_user_group_at:
          h.request_closed_user_group_at = datetime.datetime.now()
          h.save()
    if health_workers:
      dataset = tablib.Dataset(
        *[(fix_phone(i.vodacom_phone), i.surname or u"") for i in health_workers],
        headers=["phone_number", "name"])
      email = EmailMessage(u"Closed User Group Request %s" % (datetime.datetime.now(), ),
                           u"Please add the attached users to the closed user group.  Thanks!",
                           opts.src_email,
                           [opts.dst_email])
      filename = datetime.datetime.now().strftime("cug-request-%Y%m%d-%H%M%S.xls")
      email.attach(filename, dataset.xls, "application/vnd.ms-excel")
      email.send()

if __name__ == "__main__":
  main()



