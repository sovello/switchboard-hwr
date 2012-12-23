# Copyright 2012 Switchboard, Inc


import datetime
import json
import time

from django.core import serializers
from django.http import HttpResponse

from sb import http
from sb.healthworker import models


OK = 0
ERROR_INVALID_INPUT = -1

def _specialty_to_dictionary(specialty):
  "Convert a Specialty to a dictionary suitable for JSON encoding"
  return {"created_at": specialty.created_at,
          "updated_at": specialty.updated_at,
          "id": specialty.id,
          "abbreviation": specialty.abbreviation,
          "title": specialty.title}

def on_specialty_index(request):
  """Get a list of specialties"""
  specialties = models.Specialty.objects.all()
  return http.to_json_response(
      {"status": OK,
       "specialties": map(_specialty_to_dictionary, specialties)})

def on_health_worker_index(request):
  "Get information about a health worker"
  health_workers = models.MCTRegistration.objects
  num = request.GET.get("registration")
  name = request.GET.get("name")
  count = request.GET.get("count", 20)
  try:
    count = int(count)
  except (ValueError, TypeError), error:
    count = 20
  if num:
    health_workers = health_workers.filter(registration_number=num)
  if name:
    # FIXME: do levenshtein
    health_workers = health_workers.filter(name__istartswith=name)

  health_worker_dicts = []
  for h in health_workers.all()[:count]:
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

def on_region_index(request):
  regions = models.Region.objects
  for (query_param, key) in [
      ("parent_region_id", "parent_region_id"),
      ("type", "type__title__iexact"),
      ("title", "title__istartswith")]:
    val = request.GET.get(query_param)
    if val:
      regions = regions.filter(**{key: val})
  regions = regions.prefetch_related('type').all()
  response = {
      "status": OK,
      "regions": map(_region_to_dictionary, regions)}
  return http.to_json_response(response)

def _facility_to_dictionary(facility):
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
      "place_type": facility.place_type,
      "region_id": facility.region_id,
      "created_at": facility.created_at,
      "updated_at": facility.updated_at}

def on_facility_index(request):
  facilities = models.Facility.objects
  title = request.GET.get("title")
  if title:
    facilities = facilities.filter(title__istartswith=title)
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
  facilities = facilities.prefetch_related("type")
  facilities = facilities.all()
  response = {
      "status": OK,
      "facilities": map(_facility_to_dictionary, facilities)}
  return http.to_json_response(response)

