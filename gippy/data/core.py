#!/usr/bin/env python

import os, sys
import argparse
import ogr 
import datetime
import glob
from shapely.wkb import loads
from shapely.geometry import shape
import traceback
import gippy
import agspy.utils.dateparse as dateparse
from pdb import set_trace

def VerboseOut(txt, level=1):
    if gippy.Options.Verbose() >= level: print txt

class Data(object):
    """ Base class for data objects """
    name = ''
    sensors = {}
    rootdir = ''
    _tiles_vector = ''
    _tiles_attribute = ''

    def __init__(self, site=None, tiles=None, date=None, products=None):
        """ Locate data matching vector location (or tiles) and date """
        self.site = site
        # Calculate spatial extent
        if tiles is not None:
            self.tile_coverage = dict((t,1) for t in tiles)
            self.tiles = tiles
        elif site is not None:
            self.tile_coverage = cls.vector2tiles(gippy.GeoVector(site))
            self.tiles = self.tile_coverage.keys()
        else:
            self.tile_coverage = dict((t,1) for t in os.listdir(self.path()))
        self.tiles = {}
        self.date = date
        for t in self.tile_coverage.keys(): self.tiles[t] = {}
        self.products = {}

    def read(self):
        return gippy.GeoImage(self.filename)

    def filename(self,product,tile=None):
        """ Return filename for given product (either given tile or mosaic) """
        if tile is not None:
            return self.tiles[tile]['products'][product]
        else:
            return self.products['product']

    @classmethod
    def path(cls,tile='',date=''):
        """ Path to date or tile directory (assuming tiledir/datedir structure """
        if tile == '':
            return cls.rootdir
        elif date == '':
            return os.path.join(cls.rootdir, tile)
        else:
            return os.path.join(cls.rootdir, tile, date)

    @classmethod
    def inventory(cls,site, tiles, dates, days, products=None):
        return DataInventory(cls, site, tiles, dates, days, products)

    @property
    def get_products(self):
        """ Return list of products that exist for all tiles """
        products = []
        for t in self.tiles:
            products.extend(self.tiles[t]['products'].keys())
        return sorted(set(products))

    @classmethod
    def find_dates(cls, tile):
        """ Get list of dates for tile """
        return [datetime.datetime.strptime(os.path.basename(d),'%Y%j').date() for d in os.listdir(cls.path(tile))]

    @classmethod
    def sensor_names(cls):
        """ All possible sensor names """
        return sorted(cls.sensors.values())

    @classmethod 
    def get_tiles_vector(cls):
        """ Get GeoVector of sensor grid """
        return gippy.GeoVector("PG:dbname=geodata host=congo port=5432 user=ags", layer=cls._tiles_vector)

    @classmethod
    def vector2tiles(cls, vector):
        """ Return matching tiles and coverage % for provided vector """
        import osr
        geom = vector.union()
        ogrgeom = ogr.CreateGeometryFromWkb(geom.wkb)
        tvector = cls.get_tiles_vector()
        tlayer = tvector.layer
        trans = osr.CoordinateTransformation(vector.layer.GetSpatialRef(), tlayer.GetSpatialRef())
        ogrgeom.Transform(trans)
        geom = loads(ogrgeom.ExportToWkb())
        tlayer.SetSpatialFilter(ogrgeom)
        tiles = {}
        tlayer.ResetReading()
        feat = tlayer.GetNextFeature()
        fldindex = feat.GetFieldIndex(cls._tiles_attribute)
        while feat is not None:
            tgeom = loads(feat.GetGeometryRef().ExportToWkb())
            area = geom.intersection(tgeom).area
            if area != 0: 
                tile = str(feat.GetField(fldindex))
                if len(tile) == 5: tile = '0' + tile
                tiles[tile] = area/geom.area
            feat = tlayer.GetNextFeature()
        return tiles

class DataInventory(object):
    """ Base class for data inventories """
    # redo color, combine into ordered dictionary
    _colororder = ['bright yellow', 'bright red', 'bright green', 'bright blue']
    _colorcodes = {
        'bright yellow':   '1;33',
        'bright red':      '1;31',
        'bright green':    '1;32',
        'bright blue':     '1;34',
        'bright purple':   '1;35',
        'bright cyan':     '1;36',
        'red':             '0;31', 
        'green':           '0;32', 
        'blue':            '0;34',     
        'cyan':            '0;36',     
        'yellow':          '0;33', 
        'purple':          '0;35',
    }

    def __init__(self, dataclass, site=None, tiles=None, dates=None, days=None, products=None):
        self.dataclass = dataclass
        self.site = site
        self.tiles = tiles
        self.temporal_extent(dates, days)
        self.AddData(dataclass, products=products)

    def __getitem__(self,date):
        return self.data[date]

    def filenames(self,sensor,product):
        """ Return dictionary (date keys) of filenames for given sensor and product if supplied """
        filenames = {}
        for date in self.dates:
            if sensor in self.dates[date]:
                filenames[date] = self.dates[date][sensor].filename(product)

    @property
    def dates(self):
        """ Get sorted list of dates """
        return [k for k in sorted(self.data)]

    @property
    def numdates(self): 
        """ Get number of dates """
        return len(self.data)

    #@property
    #def sensor_names(self):
    #    """ Get list of all sensors """
    #    return [self._colorize(k, self._colors[k]) for k in sorted(self._colors)]

    def _colorize(self,txt,color): 
        return "\033["+self._colorcodes[color]+'m' + txt + "\033[0m"

    def AddData(self, dataclass, products=None):
        """ Add additional data to this inventory (usually from different sensors """
        if self.tiles is None and self.site is not None:
            self.tiles = dataclass.vector2tiles(gippy.GeoVector(self.site))
        # get all potential matching dates for tiles
        dates = []
        for t in self.tiles:
            for date in dataclass.find_dates(t):
                day = int(date.strftime('%j'))
                if (self.start_date <= date <= self.end_date) and (self.start_day <= day <= self.end_day):
                    if date not in dates: dates.append(date)
        self.numfiles = 0
        self.data = {}
        for date in sorted(dates):
            dat = dataclass(site=self.site, tiles=self.tiles, date=date, products=products)
            self.data[date] = { dat.sensor: dat }
            self.numfiles = self.numfiles + len(dat.tiles)
        
    def temporal_extent(self, dates, days):
        """ Temporal extent (define self.dates and self.days) """
        if dates is None: dates='1984,2050'
        self.start_date,self.end_date = dateparse.range(dates)
        if days: 
            days = days.split(',')
        else: days = (1,366)
        self.start_day,self.end_day = ( int(days[0]), int(days[1]) )

    def process(self, products=['toaref'], overwrite=False, suffix='', overviews=False):
        """ Process all data in inventory """
        VerboseOut('Requested %s products for %s files' % (len(products), self.numfiles))
        # TODO only process if don't exist
        for date in self.dates:
            for sensor in self.data[date]:
                self.data[date][sensor].process(products, overwrite, suffix, overviews)
                # TODO - add completed product(s) to inventory         
        VerboseOut('Completed processing')

    def project(self, res):
        print 'Preparing data for %s dates' % len(self.dates)
        # res should default to data?
        for date in self.dates:
            for sensor in self.data[date]:
                self.data[date][sensor].project(res)

    def get_products(self, date):
        """ Get list of products for given date """
        # this doesn't handle different tiles (if prod exists for one tile, it lists it)
        prods = []
        for sensor in self.data[date]:
            for prod in self.data[date][sensor].get_products:
                prods.append(prod)
        return sorted(prods)

    def createlinks(self,hard=False):
        """ Create product links """
        for date in self.data:
            for sensor in self.data[date]:
                for t in self.data[date][sensor].tiles:
                    for p in self.data[date][sensor].tiles[t]['products']:
                        link( self.data[date][sensor].tiles[t]['products'][p], hard )

    def printcalendar(self,md=False, products=False):
        """ print calendar for raw original datafiles """
        #import calendar
        #cal = calendar.TextCalendar()
        oldyear = ''
        for date in self.dates:        
            if md:
                daystr = str(date.month) + '-' + str(date.day)
            else:
                daystr = str(date.timetuple().tm_yday)
                if len(daystr) == 1:
                    daystr = '00' + daystr
                elif len(daystr) == 2:
                    daystr = '0' + daystr
            if date.year != oldyear:
                sys.stdout.write('\n{:>5}: '.format(date.year))
                if products: sys.stdout.write('\n ')
            colors = {}
            for i,s in enumerate(self.dataclass.sensor_names()): colors[s] = self._colororder[i]

            for s in self.data[date]:
                sys.stdout.write(self._colorize('{:<6}'.format(daystr), colors[self.dataclass.sensors[s]] ))
            if products:
                sys.stdout.write('        ')
                prods = self.get_products(date)
                for p in prods:
                    sys.stdout.write(self._colorize('{:<12}'.format(p), colors[self.dataclass.sensors[s]] ))
                sys.stdout.write('\n ')
            oldyear = date.year
        sys.stdout.write('\n')
        self.legend()
        print self
        if self.site is not None:
            print 'Tile Coverage:'
            for t in sorted(self.tiles): print '%s: %2.0f%%' % (t,self.tiles[t]*100)

    def legend(self):
        sensors = sorted(self.dataclass.sensors.values())
        for i,s in enumerate(sensors):
            print self._colorize(s, self._colororder[i])
            #print self._colorize(self.dataclass.sensors[s], self._colororder[s])
        
    def __str__(self):
        if self.numfiles != 0:
            s = "Data Inventory: %s files on %s dates" % (self.numfiles,self.numdates)
        else: 
            s = 'Data Inventory: No matching files'
        return s

def link(f,hard=False):
    """ Create link to file in current directory """
    faux = f + '.aux.xml'
    if hard:
        try:
            os.link(f,os.path.basename(f))
            os.link(faux,os.path.basename(faux))
        except:
            pass
    else: 
        try:
            os.symlink(f,os.path.basename(f))
            if os.path.isfile(faux):
                os.symlink(faux,os.path.basename(faux))
        except:
            pass

def main(dataclass):
    dhf = argparse.ArgumentDefaultsHelpFormatter
    parser0 = argparse.ArgumentParser(description='%s Data Utility' % dataclass.name, formatter_class=argparse.RawTextHelpFormatter)
    subparser = parser0.add_subparsers(dest='command')

    invparser = argparse.ArgumentParser(add_help=False, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    group = invparser.add_argument_group('inventory arguments')
    group.add_argument('-s','--site',help='Vector file for region of interest', default=None)
    group.add_argument('-t','--tiles', nargs='*', help='Tile designations', default=None)
    group.add_argument('-d','--dates',help='Range of dates (YYYY-MM-DD,YYYY-MM-DD)')
    group.add_argument('--days',help='Include data within these days of year (doy1,doy2)',default=None)
    group.add_argument('-p','--products', nargs='*', help='Process/filter these products') #default=False)
    group.add_argument('-v','--verbose',help='Verbosity - 0: quiet, 1: normal, 2: debug', default=1, type=int)

    # Help
    parser = subparser.add_parser('help',help='Print extended help', parents=[invparser], formatter_class=dhf)

    # Inventory
    parser = subparser.add_parser('inventory',help='Get Inventory', parents=[invparser], formatter_class=dhf)
    parser.add_argument('--md',help='Show dates using MM-DD',action='store_true',default=False)
    

    # Processing
    parser = subparser.add_parser('process',help='Process scenes', parents=[invparser],formatter_class=dhf)
    group = parser.add_argument_group('Processing Options')
    group.add_argument('--overwrite', help='Overwrite output files if they exist', default=False, action='store_true')
    group.add_argument('--suffix', help='Append string to end of filename (before extension)',default='')
    #group.add_argument('--nooverviews', help='Do not add overviews to output', default=False, action='store_true')
    #pparser.add_argument('--link', help='Create links in current directory to output', default=False, action='store_true')
    #pparser.add_argument('--multi', help='Use multiple processors', default=False, action='store_true')
    # Project
    parser = subparser.add_parser('project',help='Create project', parents=[invparser], formatter_class=dhf)
    group = parser.add_argument_group('Project options')
    group.add_argument('--res',nargs=2,help='Resolution of output rasters', default=[30,30], type=float)

    # Links
    parser = subparser.add_parser('link',help='Link to Products', parents=[invparser], formatter_class=dhf)
    parser.add_argument('--hard',help='Create hard links instead of symbolic', default=False,action='store_true')

    # Misc
    parser_archive = subparser.add_parser('archive',help='Move files from current directory to data archive')

    args = parser0.parse_args()
    if args.command == 'help':
        parser0.print_help()
        print '\navailable products:'
        for key,val in dataclass._products.items(): 
            print '    {:<20}{:<100}'.format(key, val['description'])
        exit(1)

    gippy.Options.SetVerbose(args.verbose)
    gippy.Options.SetChunkSize(128.0)   # replace with option

    try:
        inv = dataclass.inventory(site=args.site, dates=args.dates, days=args.days, tiles=args.tiles, products=args.products)
    except Exception,e:
        print 'Error getting inventory: %s' % (e)
        VerboseOut(traceback.format_exc(), 3)
        exit(1)

    if args.command == 'inventory':
        if args.products is None:
            inv.printcalendar(args.md)
        else: inv.printcalendar(args.md,True)
        
    elif args.command == 'link':
        inv.createlinks(args.hard)

    elif args.command == 'process':
        try:
            #merrafname = fetchmerra(meta['datetime'])
            inv.process(products=args.products,overwrite=args.overwrite,suffix=args.suffix) #, nooverviews=args.nooverviews)
        except Exception,e:
            print 'Error processing: %s' % e
            VerboseOut(traceback.format_exc(), 3)

    elif args.command == 'project':
        inv.process(products=args.products) 
        inv = dataclass.inventory(site=args.site, dates=args.dates, days=args.days, tiles=args.tiles, products=args.products)
        inv.project(args.res)

    elif args.command == 'archive':
        archive()

    else:
        print 'Command %s not recognized' % cmd