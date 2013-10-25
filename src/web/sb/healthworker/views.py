# Copyright 2012 Switchboard, Inc
import csv
import datetime
import json
import logging
import re
import sys
import time
import types
import StringIO

from django.core import serializers
from django.http import HttpResponse
from django import forms
from django.db import transaction

from sb import http
from sb.healthworker import models
from sb.healthworker import stopwords
import sb.util
import sb.html

_log = logging.getLogger('sb.healthworker.views')

OK = 0
ERROR_INVALID_INPUT = -1
ERROR_INVALID_PATTERN = -2

def _log_request_json(function):
  def new_function(request):
    json = getattr(request, 'JSON', None)
    uri = request.get_full_path()
    _log.info(u'request: %r json: %r', uri, json)
    response = function(request)
    return response
  return new_function

def _specialty_to_dictionary(specialty):
  "Convert a Specialty to a dictionary suitable for JSON encoding"
  return {"created_at": specialty.created_at,
          "updated_at": specialty.updated_at,
          "id": specialty.id,
          "parent_specialty_id": specialty.parent_specialty_id,
          "is_query_subspecialties": specialty.is_query_subspecialties,
          "abbreviation": specialty.abbreviation,
          "msisdn": specialty.msisdn,
          "is_user_submitted": specialty.is_user_submitted,
          "short_title": specialty.short_title,
          "priority": specialty.priority,
          "title": specialty.title}

def on_specialty_index(request):
  """Get a list of specialties"""
  specialties = models.Specialty.objects.all()

  # Filter out user submitted specialties:
  specialties = [i for i in specialties if not i.is_user_submitted]
  specialties.sort(key=lambda i: ((sys.maxint - i.priority), i.title))
  return http.to_json_response({
    "status": OK,
    "specialties": map(_specialty_to_dictionary, specialties)})

def on_mct_payroll_index(request):
  """Get a list of ministry of tanzania payroll entries"""
  mct_payroll_entries = models.MCTPayroll.objects
  check = sb.util.safe(lambda: request.GET["check"])
  offset = sb.util.safe(lambda: int(request.GET["offset"])) or 0
  count = sb.util.safe(lambda: int(request.GET["count"])) or 100
  if check:
    mct_payroll_entries = mct_payroll_entries.filter(check_number=check)
  name = request.GET.get("name")
  if name is not None:
    mct_payroll_entries = include_similar(mct_payroll_entries, "name", name)

  mct_payroll_entries = mct_payroll_entries.all()
  mct_payroll_entries = list(mct_payroll_entries)
  total = len(mct_payroll_entries)
  mct_payroll_entries = mct_payroll_entries[offset:count]
  return http.to_json_response({
    "status": OK,
    "total": total,
    "mct_payrolls": [{
        "id": i.id,
        "name": i.name,
        "birthdate": i.birthdate,
        "designation": i.designation,
        "district": i.district,
        "specialty_id": i.specialty_id,
        "last_name": i.last_name,
        "region_id": i.region_id,
        "health_worker_id": i.health_worker_id,
        "facility_id": i.facility_id,
        "check_number": i.check_number}
      for i in mct_payroll_entries]})

def on_mct_registration_index(request):
  "Get information about a health worker"
  health_workers = models.MCTRegistration.objects
  num = request.GET.get("registration")
  count = sb.util.safe(lambda:int(request.GET["count"])) or 100
  offset = sb.util.safe(lambda:int(request.GET["offset"])) or 0
  if num:
    health_workers = health_workers.filter(registration_number=num)

  name = request.GET.get("name")
  if name is not None:
    health_workers = include_similar(health_workers, "name", name)

  health_workers = list(health_workers.all())
  total = len(health_workers)

  health_worker_dicts = []
  for h in health_workers[offset:count]:
    health_worker_dicts.append({
      "address": h.address,
      "birthdate": h.birthdate,
      "cadre": h.cadre,
      "category": h.category,
      "country": h.country,
      "created_at": h.created_at,
      "current_employer": h.current_employer,
      "dates_of_registration_full": h.dates_of_registration_full,
      "dates_of_registration_provisional": h.dates_of_registration_provisional,
      "dates_of_registration_temporary": h.dates_of_registration_temporary,
      "email": h.email,
      "employer_during_internship": h.employer_during_internship,
      "facility": h.facility.id if h.facility else None,
      "file_number": h.file_number,
      "id": h.id,
      "name": h.name,
      "qualification_final": h.qualification_final,
      "qualification_provisional": h.qualification_provisional,
      "qualification_specialization_1": h.qualification_specialization_1,
      "qualification_specialization_2": h.qualification_specialization_2,
      "registration_number": h.registration_number,
      "registration_type": h.registration_type,
      "specialties": [i.id for i in h.specialties.all()],
      "specialty": h.specialty,
      "specialty_duration": h.specialty_duration,
      "updated_at": h.updated_at})
  response = {
      "status": OK,
      "total": total,
      "health_workers": health_worker_dicts}
  return http.to_json_response(response)

def _region_to_dictionary(region):
  if region is None:
    return None
  else:
    return {
        "title": region.title,
        "type": region.type.title if region.type is not None else None,
        "id": region.id,
        "parent_region_id": region.parent_region_id,
        "created_at": region.created_at,
        "updated_at": region.updated_at}

def include_similar(query_set, field, value, algorithm='trigram', distance=0.5):
  where = ["is_similar(%%s, %s, '%s', %.2f)" % (field, algorithm, distance)]
  where_params = [value]
  return query_set.extra(where=where, params=where_params)

def on_region_type_index(request):
  return http.to_json_response({
    "status": OK,
    "region_types": [
      {"title": r.title,
       "created_at": r.created_at,
       "updated_at": r.updated_at,
       "id": r.id} for r in models.RegionType.objects.all()
    ]})

def on_region_index(request):
  regions = models.Region.objects
  for (query_param, key) in [
      ("parent_region_id", "parent_region_id"),
      ("type", "type__title__iexact")]:
    val = request.GET.get(query_param)
    if val:
      regions = regions.filter(**{key: val})
  title = request.GET.get("title")
  if title:
    title = stopwords.fix_district_query(title)
    regions = include_similar(regions, "healthworker_region.title", title, 'levenshtein', 2)
  regions = regions.prefetch_related("type").all()

  response = {
      "status": OK,
      "regions": map(_region_to_dictionary, regions)}
  return http.to_json_response(response)

def _facility_to_dictionary(facility):
  region = None
  r = facility.region
  if r is not None:
    region = {
      "title": r.title,
      "id": r.id,
      "parent_region_id": r.parent_region_id,
      "type_id": r.type_id}
  return {
      "id": facility.id,
      "title": facility.title,
      "address": facility.address,
      "type": facility.type.title if facility.type else None,
      "place_type": facility.place_type,
      "serial_number": facility.serial_number,
      "owner": facility.owner,
      "ownership_type": facility.ownership_type,
      "phone": facility.phone,
      "region_id": facility.region_id,
      "region": region,
      "created_at": facility.created_at,
      "updated_at": facility.updated_at}

def on_facility_index(request):
  facilities = models.Facility.objects
  region_id = request.GET.get("region")
  if region_id:
    # compute subregions here.
    region_ids = set()
    try:
      region = models.Region.objects.get(id=region_id)
    except models.Region.DoesNotExist:
      pass
    else:
      region_ids.add(region.id)
      region_ids.update(region.subregion_ids())
    facilities = facilities.filter(region_id__in=region_ids)
  facility_type = sb.util.safe(lambda:int(request.GET["type"]))
  if facility_type:
    facilities = facilities.filter(type_id=facility_type)

  title = request.GET.get("title")
  if title:
    title = stopwords.fix_facility_query(title)
    facilities = include_similar(facilities, "title", title, 'levenshtein', 2)

  facilities = facilities.prefetch_related("type")
  facilities = facilities.all()
  facilities = filter(lambda f: not f.is_user_submitted, facilities)
  facilities = list(facilities)
  facilities.sort(key=lambda i:(sys.maxint - i.type.priority, i.title))
  response = {
      "status": OK,
      "facilities": map(_facility_to_dictionary, facilities)}
  return http.to_json_response(response)

_address_pat = re.compile(u"^.{1,255}$")
_email_pat = re.compile(u"^.+@.+$")
_name_pat = re.compile(u"^.{1,255}$")

def string_parser(pattern=None, required=False, min_length=None, max_length=None, strip=True):
  def parser(value):
    if value is None:
      if required:
        return None, ERROR_INVALID_INPUT
      else:
        return value, None
    if not isinstance(value, unicode):
      return None, ERROR_INVALID_INPUT
    if strip:
      value = value.strip()
    if pattern is not None:
      pat = re.compile(pattern) if isinstance(pattern, types.StringTypes) else pattern
      if not pat.match(value):
        return None, ERROR_INVALID_INPUT
    if min_length is not None and len(value) < min_length:
      return None, ERROR_INVALID_INPUT
    if max_length is not None and len(value) > max_length:
      return None, ERROR_INVALID_INPUT
    return value, None
  return parser

def dictionary_parser(key_to_parser):
  def parser(data):
    if not data:
      return None, {"status": ERROR_INVALID_INPUT, "key": None}
    if not isinstance(data, dict):
      return None, {"status": ERROR_INVALID_INPUT, "key": None}
    result = {}
    for key, parser in key_to_parser.items():
      v = data.get(key)
      v, status = parser(v)
      if status:
        return None, {"key": key, "status": status}
      result[key] = v
    return result, None
  return parser

def list_parser(parser, required=None):
  def parser0(values):
    if not isinstance(values, (list, tuple, type(None))):
      return None, ERROR_INVALID_INPUT
    if not values:
      if not required:
        return [], None
      else:
        return None, ERROR_INVALID_INPUT
    result = []
    for v in values:
      parsed, status = parser(v)
      if status:
        return None, status
      else:
        result.append(parsed)
    return result, None
  return parser0

def foreign_key_parser(model_class, required=None):
  def parser(value):
    if value is None:
      if required:
        return None, ERROR_INVALID_INPUT
      else:
        return None, None
    try:
      return model_class.objects.get(id=value), None
    except model_class.DoesNotExist:
      return None, ERROR_INVALID_INPUT
  return parser

def date_parser(required=None):
  def parser(value):
    if not isinstance(value, (dict, type(None))):
      return None, ERROR_INVALID_INPUT
    if not value:
      if required:
        return None, ERROR_INVALID_INPUT
      else:
        return None, None
    result = sb.util.safe(lambda: datetime.date(value["year"], value["month"], value["day"]))
    return result, None
  return parser

def parse_healthworker_input(data):
  parser = dictionary_parser({
    "address": string_parser(pattern="^.{0,255}$", required=False),
    "birthdate": date_parser(required=False),
    "country": string_parser(min_length=2, max_length=3, required=False),
    "email": string_parser(pattern="^.+@.+$", required=False),
    "facility": foreign_key_parser(models.Facility, required=False),
    "language": string_parser(max_length=16, required=False),
    "name": string_parser(min_length=1, required=True),
    "specialties": list_parser(foreign_key_parser(models.Specialty, required=False)),
    "vodacom_phone": string_parser(required=False, max_length=255),
    "surname": string_parser(required=False, max_length=255),
    "mct_registration_number": string_parser(required=False, max_length=255),
    "mct_payroll_number": string_parser(required=False, max_length=255),
    "other_phone": string_parser(required=False, max_length=255)})
  return parser(data)

def on_health_workers_save(request):
  if not request.is_json:
    return http.to_json_response({
      "status": ERROR_INVALID_INPUT,
      "message": "expecting JSON input"})
  data, error = parse_healthworker_input(request.JSON)
  if error:
    return http.to_json_response({"status": error["status"], "key": error.get("key")})

  with transaction.commit_on_success():
    health_worker = None

    workers = list(models.HealthWorker.objects.filter(vodacom_phone=data['vodacom_phone'])[:1])
    if workers:
      health_worker = workers[0]
    else:
      health_worker = models.HealthWorker()
      health_worker.vodacom_phone = data["vodacom_phone"]

    health_worker.address = data["address"]
    health_worker.birthdate = data["birthdate"]
    health_worker.name = data["name"]
    health_worker.country = data["country"]
    health_worker.email = data["email"]
    health_worker.facility = data["facility"]
    for i in data["specialties"]:
      health_worker.save()
      health_worker.specialties.add(i)
    health_worker.other_phone = data["other_phone"]
    health_worker.language = data["language"]
    health_worker.mct_registration_num = data["mct_registration_number"]
    health_worker.mct_payroll_num = data["mct_payroll_number"]
    health_worker.surname = data["surname"]

    health_worker.save()
    health_worker.auto_verify()

    return http.to_json_response({"status": OK, "id": health_worker.id})

def on_health_workers_index(request):
  """Get an index of health care workers"""
  health_workers = models.HealthWorker.objects.all()
  health_workers = health_workers.prefetch_related("specialties", "facility").all()

  return http.to_json_response(
    {"status": OK,
     "health_workers": [
       {"id": i.id,
        "name": i.name,
        "country": i.country,
        "vodacom_phone": i.vodacom_phone,
        "created_at": i.created_at,
        "updated_at": i.updated_at,
        "language": i.language,
        "mct_registration_num": i.mct_registration_num,
        "mct_payroll_num": i.mct_payroll_num,
        "verification_state": i.verification_state,
        "email": i.email,
        "birthdate": i.birthdate,
        "address": i.address,
        "other_phone": i.other_phone,
        "specialties": [s.id for s in i.specialties.all()],
        "facility": i.facility_id}
       for i in health_workers if i.verification_state]})

@_log_request_json
def on_health_worker(request):
  if request.method == "POST":
    return on_health_workers_save(request)
  else:
    return on_health_workers_index(request)


def on_facility_type_index(request):
  facility_types = [{"id": f.id,
                     "created_at": f.created_at,
                     "updated_at": f.updated_at,
                     "priority": f.priority,
                     "title": f.title}
                     for f in models.FacilityType.objects.all()]
  facility_types.sort(key=lambda i: (sys.maxint - i['priority'], i['title']))
  response = {"status": OK, "facility_types": facility_types}
  return http.to_json_response(response)

def on_specialty(request):
  if request.method != "POST":
    return on_specialty_index(request)
  else:
    return on_specialty_create(request)

def on_specialty_create(request):
  if not request.is_json:
    return http.to_json_response({
      "status": ERROR_INVALID_INPUT,
      "message": "expecting JSON input"})
  data, error = parse_specialty_input(request.JSON)
  if error:
    return http.to_json_response({"status": error["status"], "key": error.get("key")})

  with transaction.commit_on_success():
    if list(models.Specialty.objects.filter(title=data["title"], parent_specialty=data["parent_specialty"]).all()):
      return http.to_json_response({"status": ERROR_INVALID_INPUT})
    specialty = models.Specialty()
    specialty.title = data["title"]
    specialty.parent_specialty = data["parent_specialty"]
    specialty.msisdn = data["msisdn"]
    specialty.is_user_submitted = True
    specialty.save()
    return http.to_json_response({"status": OK, "id": specialty.id})

def parse_specialty_input(data):
  parser = dictionary_parser({
    "title": string_parser(pattern="^.{1,255}$", required=False),
    "msisdn": string_parser(pattern="^.{1,255}$", required=False),
    "parent_specialty": foreign_key_parser(models.Specialty, required=False)})
  return parser(data)

def on_facility(request):
  if request.method != "POST":
    return on_facility_index(request)
  else:
    return on_facility_create(request)

def parse_facility_input(data):
  parser = dictionary_parser({
    "title": string_parser(pattern="^.{1,255}$", required=True),
    "address": string_parser(pattern="^.{1,1000}$", required=False),
    "msisdn": string_parser(pattern="^.{1,255}$", required=False),
    "type": foreign_key_parser(models.FacilityType, required=False),
    "region": foreign_key_parser(models.Region, required=False)})
  return parser(data)

def on_facility_create(request):
  if not request.is_json:
    return http.to_json_response({
      "status": ERROR_INVALID_INPUT,
      "message": "expecting JSON input"})
  data, error = parse_facility_input(request.JSON)
  if error:
    return http.to_json_response({"status": error["status"], "key": error.get("key")})
  with transaction.commit_on_success():
    facility = models.Facility()
    facility.title = data["title"]
    facility.address = data["address"]
    facility.region = data["region"]
    facility.msisdn = data["msisdn"]
    facility.is_user_submitted = True
    facility.save()
    return http.to_json_response({"status": OK, "id": facility.id})

class UploadForm(forms.Form):
  members = forms.FileField()

def normalize_tz_phone(phone_number):
  if phone_number.startswith('255'):
    return '+' + phone_number
  elif phone_number.startswith('07'):
    return '+255' + phone_number[1:]
  elif phone_number.startswith('7'):
    return '+255' + phone_number
  else:
    return phone_number

def cug(request):
  if request.method == "POST":
    form = UploadForm(request.POST, request.FILES)
    if form.is_valid():
      members_file = request.FILES["members"]
      members_file_bytes = members_file.read()
      if '\n' not in members_file_bytes:
        members_file_bytes = members_file_bytes.replace('\r', '\r\n')
      if '\r' not in members_file_bytes:
        members_file_bytes = members_file_bytes.replace('\n', '\r\n')
      member_buf = StringIO.StringIO(members_file_bytes)
      entries = csv.DictReader(member_buf)
      phone_numbers = []
      for entry in entries:
        if "phone" in entry:
          phone = entry["phone"]
          phone = normalize_tz_phone(phone)
          if phone:
            phone_numbers.append(phone)
      with transaction.commit_on_success():
        hws = models.HealthWorker.objects.filter(vodacom_phone__in=phone_numbers)
        for hw in hws:
          hw.set_closed_user_group(True)
  else:
    form = UploadForm()
  return sb.html.render_response(request,
                                 "sb.healthworker",
                                 "cug.html",
                                 form=form)
