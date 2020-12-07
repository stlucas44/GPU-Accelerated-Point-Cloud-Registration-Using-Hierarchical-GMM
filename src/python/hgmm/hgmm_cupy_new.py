# -*- coding: utf-8 -*-
"""hgmm_cupy_new.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1dRqykhVzDFJBgGjLjqWxl8I0LkAD0Twn
"""

from __future__ import print_function
from __future__ import division
import matplotlib.pyplot as plt
from sklearn import cluster, datasets, mixture
import numpy as np
from scipy.stats import multivariate_normal
from sklearn.datasets import make_spd_matrix
plt.rcParams["axes.grid"] = False
import os
#os.environ['NUMBAPRO_LIBDEVICE'] = "/usr/local/cuda-10.0/nvvm/libdevice"
#os.environ['NUMBAPRO_NVVM'] = "/usr/local/cuda-10.0/nvvm/lib64/libnvvm.so"
#from numba import cuda
#from numba.types import float32
import math
import cupy as cp
from collections import namedtuple
import open3d as o3
import transformations as trans

eps = 1.0e-15
n_node = 8

# class node:
#     def __init__(self):
#         self.mixingCoeff = 0.0
#         self.mean = np.zeros(3,dtype=np.float32)
#         self.covar = np.identity(3,dtype= np.float32)

#     def set_mixingCoeff(self,mixingCoeff):
#         self.mixingCoeff = mixingCoeff

#     def set_mean(self,mean):
#         self.mean = mean

#     def set_covar(self,covar):
#         self.covar = covar

# class moment:
#     def __init__(self):
#         self.zero = 0.0
#         self.one = np.zeros(3,dtype= np.float32)
#         self.two = np.zeros((3,3),dtype= np.float32)

#     def set_zero(self,zero):
#         self.zero = zero

#     def set_one(self,one):
#         self.one = one

#     def set_two(self,two):
#         self.two = two

def gaussianPdf(data,mu,cov):
    d = data - mu
    #print(type(cov))
    det = np.linalg.det(cov)
    epsarr = eps*np.ones((len(d)),dtype = np.float32)
    #if(det < eps):
    #    return 0.0
    c = 1.0/(np.power(det,0.5) * np.power(2.0 * np.pi, len(data) *0.5))
    ep = -0.5 * np.matmul(d,np.matmul(np.linalg.inv(cov),d.T))
    p = det < epsarr
    return p * c * np.exp(ep)

def logLikelihoodValue(mixingCoeff,mean,covar,data,j0,j1):
    q = 0.0
    j0 = int(j0)
    j1 = int(j1)
    #print("j0 is: ",j0)
    #print("j1 is: ",j1)
    #print("Points are of: ",data.shape[0])
    for i in range (data.shape[0]):
        m = mixingCoeff[j0:j1]
        temp = np.where(m < eps, 0.0, m * gaussianPdf(data[i],mean[j0:j1],covar[j0:j1]))
        q = q + np.log(max(np.sum(temp),eps))

    return q

def complexity(cov):
  #pdb.set_trace()
    lamds,vec = np.linalg.eig(cov)
    lamds[::-1].sort()
    return lamds[2]/np.sum(lamds)

def child(j):
    return (j+1) * n_node

def level(l):
    return n_node * (cp.power(n_node,l) -1 )/ (n_node -1)

def accumulate(momentZero,momentOne,momentTwo,gamma,data):
  i = 0
  while(i < len(momentZero)):
      if (momentZero[i] <  eps):
          i = i + 1
          continue
      momentZero[i] = momentZero[i] + gamma[i]
      momentOne[i] = momentOne[i] + gamma[i]*data
      momentTwo[i] = momentTwo[i] + gamma[i]*(np.matmul(data.T,data))
      i = i + 1


def mlEstimator(momentZero,momentOne,momentTwo,nTotal,ld):

  i = 0
  while(i < len(momentZero)):
        if (momentZero[i] <  ld):
          mixingCoeff = 0.0
          mean = np.zeros(3,dtype = np.float32)
          covar = np.identity(3,dtype = np.float32)
        else:
            mixingCoeff = float(momentZero / nTotal)
            mean = momentOne/float(moment.zero)
            covar = momentTwo/float(momentZero) - mean * (mean).T
        i = i + 1
  #print("The mixing coefficient is before return is:",n1.mixingCoeff)
  return mixingCoeff,mean,covar

import pdb
def buildGMMTree(points,maxTreeLevel,ls,ld):
  nTotal = int(n_node * (cp.power(n_node,maxTreeLevel) -1 )/(n_node-1))
  cp.random.seed(nTotal)
  idxs = cp.random.randint(nTotal,size = nTotal)
  sig2 = 0.00034
  mixingCoeff = np.zeros(nTotal,dtype = np.float32)
  mean = np.zeros((nTotal,3),dtype = np.float32)
  covar = np.zeros((nTotal,3,3),dtype= np.float32)
  for i in range(nTotal):
    mixingCoeff[i] = 1.0/n_node
    mean[i] = points[int(idxs[i])]
    covar[i] = np.identity(3) * sig2

  parentIdx = -1*np.ones(points.shape[0],dtype = int)
  currentIdx = np.zeros(points.shape[0],dtype = int)

  for l in range(maxTreeLevel):
    prevQ = 0.0
    while (True):
        print("Level: ",l)
        print("The current IDx values are:")
        print(currentIdx[0:21])
        momentZero,momentsOne,momentsTwo = gmmTreeEStep(points,mixingCoeff,mean,covar,parentIdx,currentIdx,maxTreeLevel)
        gmmTreeMStep(momentZero,momentsOne,momentsTwo,l,mixingCoeff,mean,covar,points.shape[0],ld)
        q = logLikelihoodValue(mixingCoeff,mean,covar,points,level(l),level(l+1))
        print("Likelihood value is: ",q)
        print("The difference is the value is ",q - prevQ)
        if (np.abs(q - prevQ) < ls):
            break
        prevQ = q
    parentIdx = cp.copy(currentIdx)
  #print("Nodes is",nodes)
  return mixingCoeff,mean,covar

def gmmTreeEStep(points,mixingCoeff,mean,covar,parentIdx,currentIdx,maxTreeLevel):
  nTotal = int(n_node * (np.power(n_node,maxTreeLevel) -1 )/(n_node-1))
  momentsZero = np.zeros(nTotal,dtype = np.float32)
  momentsOne = np.zeros((nTotal,3),dtype = np.float32)
  momentsTwo = np.zeros((nTotal,3,3),dtype = np.float32)

  #print("Entered into the E Step")
  for i in range(points.shape[0]):
    j0 = int(child(parentIdx[i]))
    gamma = np.zeros(n_node)
    gamma = mixingCoeff[j0:j0+n_node] * gaussianPdf(points[i],mean[j0:j0+n_node],covar[j0:j0+n_node])

    den = np.sum(gamma)
    if (float(den) > eps):
      gamma = gamma/den
    else:
      gamma = np.zeros(n_node)

    accumulate(momentsZero[j0:j0+n_node],momentsOne[j0:j0+n_node],momentsTwo[j0:j0+n_node],gamma,points[i])

    maxj = np.argmax(gamma)
    currentIdx[i] = j0 + maxj
  return momentsZero,momentsOne,momentsTwo

def gmmTreeMStep(momentsZero,momentsOne,momentsTwo,l,mixingCoeff,mean,covar,n_points,ld):
  lb = int(level(l))
  le = int(level(l+1))
  #print("Values of lb and le are:",lb,le)
  for i in range(lb,le):
    mixingCoeff[lb:lb+le],mean[lb:lb+le],covar[lb:lb+le] = mlEstimator(momentsZero[lb:lb+le],momentsOne[lb:lb+le],momentsTwo[lb:lb+le],n_points,ld)
    #print("The mixing coefficient is after return is:",nodes[i].mixingCoeff)


def gmmTreeRegESTep(points,mixingCoeff,mean,covar,maxTreeLevel,lc):
  #print("Node value is: ",nodes[0].mixingCoeff,nodes[0].mean,nodes[0].covar)
  nTotal = int(n_node * (np.power(n_node,maxTreeLevel) -1 )/(n_node-1))
  momentsZero = np.zeros(nTotal,dtype = np.float32)
  momentsOne = np.zeros((nTotal,3),dtype = np.float32)
  momentsTwo = np.zeros((nTotal,3,3),dtype = np.float32)

  for i in range(points.shape[0]):
    searchID = -1
    gamma = np.zeros(n_node)
    for l in range(maxTreeLevel):
      j0 = int(child(searchID))
      gamma = mixingCoeff[j0:j0+n_node] * gaussianPdf(points[i],mean[j0:j0+n_node],covar[j0:j0+n_node])

      den = np.sum(gamma)
      if (float(den) > eps):
        gamma = gamma/den
      else:
        gamma = np.zeros(n_node)

      searchID = np.argmax(gamma)
      searchID = searchID + j0
      if (complexity(covar[searchID]) <= lc):
        break
      accumulate(momentsZero[searchID],momentsZero[searchID],momentsZero[searchID],gamma[searchID- j0],points[i])

  return momentsZero,momentsOne,momentsTwo

import abc
import six

@six.add_metaclass(abc.ABCMeta)
class Transformation():
    def __init__(self):
        pass

    def transform(self, points,
                  array_type=o3.utility.Vector3dVector):
        if isinstance(points, array_type):
            return array_type(self._transform(np.asarray(points)))
        return self._transform(points)

    @abc.abstractmethod
    def _transform(self, points):
        return points


class RigidTransformation(Transformation):
    """Rigid Transformation
    Args:
        rot (numpy.ndarray, optional): Rotation matrix.
        t (numpy.ndarray, optional): Translation vector.
        scale (Float, optional): Scale factor.
    """
    def __init__(self, rot=np.identity(3),
                 t=np.zeros(3), scale=1.0):
        super(RigidTransformation, self).__init__()
        self.rot = rot
        self.t = t
        self.scale = scale

    def _transform(self, points):
        return self.scale * np.dot(points, self.rot.T) + self.t

    def inverse(self):
        return RigidTransformation(self.rot.T, -np.dot(self.rot.T, self.t),
                                   1.0 / self.scale)

def skew(x):
    """
    skew-symmetric matrix, that represent
    cross products as matrix multiplications.
    Args:
        x (numpy.ndarray): 3D vector.
    Returns:
        3x3 skew-symmetric matrix.
    """
    return np.array([[0.0, -x[2], x[1]],
                     [x[2], 0.0, -x[0]],
                     [-x[1], x[0], 0.0]])


def twist_mul(tw, rot, t, linear=False):
    """
    Multiply twist vector and transformation matrix.
    Args:
        tw (numpy.ndarray): Twist vector.
        rot (numpy.ndarray): Rotation matrix.
        t (numpy.ndarray): Translation vector.
        linear (bool, optional): Linear approximation.
    """
    tr, tt = twist_trans(tw, linear=linear)
    return np.dot(tr, rot), np.dot(t, tr.T) + tt

def twist_trans(tw, linear=False):
    """
    Convert from twist representation to transformation matrix.
    Args:
        tw (numpy.ndarray): Twist vector.
        linear (bool, optional): Linear approximation.
    """
    if linear:
        return np.identity(3) + skew(tw[:3]), tw[3:]
    else:
        twd = np.linalg.norm(tw[:3])
        if twd == 0.0:
            return np.identity(3), tw[3:]
        else:
            ntw = tw[:3] / twd
            c = np.cos(twd)
            s = np.sin(twd)
            tr = c * np.identity(3) + (1.0 - c) * np.outer(ntw, ntw) + s * skew(ntw)
            return tr, tw[3:]

EstepResult = namedtuple('EstepResult', ['momemtZero','momemtOne','momemtTwo'])
MstepResult = namedtuple('MstepResult', ['transformation', 'q'])

class GMMTree():
    """GMM Tree
    Args:
        source (numpy.ndarray, optional): Source point cloud data.
        tree_level (int, optional): Maximum depth level of GMM tree.
        lambda_c (float, optional): Parameter that determine the pruning of GMM tree
    """
    def __init__(self, source=None, tree_level=2, lambda_c=0.01):
        self._source = source
        self._tree_level = tree_level
        self._lambda_c = lambda_c
        self._tf_type = RigidTransformation
        self._tf_result = self._tf_type()
        self._callbacks = []
        if not self._source is None:
            self._mixingCoeff,self._mean,self._covar = buildGMMTree(self._source,
                                                 self._tree_level,
                                                 80, 1.0e-4)

    def set_source(self, source):
        self._source = source
        self._mixingCoeff,self._mean,self._covar = buildGMMTree(self._source,
                                             self._tree_level,
                                             80, 1.0e-4)

    def set_callbacks(self, callbacks):
        self._callbacks = callbacks

    def expectation_step(self, target):
        # print("Node 1 value:",self._nodes[0].mixingCoeff)
        # print("Node 5 value:",self._nodes[5].mixingCoeff)
        # print("Node 10 value:",self._nodes[10].mixingCoeff)
        momemtZero,momentOne,momentTwo = gmmTreeRegESTep(target, self._mixingCoeff,self._mean,self._covar, self._tree_level, self._lambda_c)
        return EstepResult(momemtZero,momentOne,momentTwo)

    def maximization_step(self, estep_res, trans_p):
        momentsZero,momentsOne,momentsTwo = estep_res.momemtZero, estep_res.momemtOne, estep_res.momemtTwo
        # print("The length of moments are: ",n)
        # print("The moment is:",moments[0].zero,moments[0].one,moments[0].two)
        amat = np.zeros((n * 3, 6))
        bmat = np.zeros(n * 3)
        for i in range(len(momentsZero)):
            if momentsZero[i] < np.finfo(np.float32).eps:
                continue
            lmd, nn = np.linalg.eigh(self._covar[i])
            s = momentsOne[i] / momentsZero[i]
            nn = np.multiply(nn, np.sqrt(m.zero / lmd))
            sl = slice(3 * i, 3 * (i + 1))
            bmat[sl] = (np.dot(nn.T, self._nodes[i].mean.T) - np.dot(nn.T, s.T)).T
            amat[sl, :3] = np.cross(s, nn.T)
            amat[sl, 3:] = nn.T
        x, q, _, _ = np.linalg.lstsq(amat, bmat, rcond=-1)
        rot, t = twist_mul(x, trans_p.rot, trans_p.t)
        return MstepResult(RigidTransformation(rot, t), q)

    def registration(self, target, maxiter=20, tol=1.0e-4):
        q = None
        for _ in range(maxiter):
            t_target = self._tf_result.transform(target)
            estep_res = self.expectation_step(t_target)
            #print("Output of expectation Step:",estep_res)
            res = self.maximization_step(estep_res, self._tf_result)
            #print("Output of maximization Step:",res)
            self._tf_result = res.transformation
            for c in self._callbacks:
                c(self._tf_result.inverse())
            if not q is None and abs(res.q - q) < tol:
                break
            q = res.q
        return MstepResult(self._tf_result.inverse(), res.q)

def estimate_normals(pcd, params):
    if o3.__version__ >= '0.8.0.0':
        pcd.estimate_normals(search_param=params)
        pcd.orient_normals_to_align_with_direction()
    else:
        o3.estimate_normals(pcd, search_param=params)
        o3.orient_normals_to_align_with_direction(pcd)


def prepare_source_and_target_rigid_3d(source_filename,
                                       noise_amp=0.001,
                                       n_random=500,
                                       orientation=np.deg2rad([0.0, 0.0, 30.0]),
                                       translation=np.zeros(3),
                                       normals=False):
    source = o3.io.read_point_cloud(source_filename)
    source = o3.geometry.PointCloud.voxel_down_sample(source, 0.005)
    print(source)
    target = copy.deepcopy(source)
    tp = np.asarray(target.points)
    np.random.shuffle(tp)
    rg = 1.5 * (tp.max(axis=0) - tp.min(axis=0))
    rands = (np.random.rand(n_random, 3) - 0.5) * rg + tp.mean(axis=0)
    target.points = o3.utility.Vector3dVector(np.r_[tp + noise_amp * np.random.randn(*tp.shape), rands])
    ans = trans.euler_matrix(*orientation)
    ans[:3, 3] = translation
    target.transform(ans)
    if normals:
        estimate_normals(source, o3.geometry.KDTreeSearchParamHybrid(radius=0.3, max_nn=50))
        estimate_normals(target, o3.geometry.KDTreeSearchParamHybrid(radius=0.3, max_nn=50))
    return source, target

def registration_gmmtree(source, target, maxiter=20, tol=1.0e-4,
                         callbacks=[], **kargs):
    cv = lambda x: np.asarray(x.points if isinstance(x, o3.geometry.PointCloud) else x)
    gt = GMMTree(cv(source), **kargs)
    gt.set_callbacks(callbacks)
    return gt.registration(cv(target), maxiter, tol)

import copy
# load source and target point cloud
source,target = prepare_source_and_target_rigid_3d('bunny.pcd')
# transform target point cloud
#th = np.deg2rad(30.0)

#target.transform(np.array([[np.cos(th), -np.sin(th), 0.0, 0.0],
#                           [np.sin(th), np.cos(th), 0.0, 0.0],
#                           [0.0, 0.0, 1.0, 0.0],
#                           [0.0, 0.0, 0.0, 1.0]]))
source = o3.geometry.PointCloud.voxel_down_sample(source, 0.005)
target = o3.geometry.PointCloud.voxel_down_sample(target, 0.005)
#sCheck = np.asarray(source.points)
#tCheck = np.asarray(target.points)
#print("Source points are:")
#print(sCheck[0:5])
#print("Target points are:")
#print(tCheck[0:5])
print(source)
# compute cpd registration
tf_param, _ = registration_gmmtree(source, target)
result = copy.deepcopy(source)
result.points = tf_param.transform(result.points)

# draw result
source.paint_uniform_color([1, 0, 0])
target.paint_uniform_color([0, 1, 0])
result.paint_uniform_color([0, 0, 1])
o3.visualization.draw_geometries([source, target, result])

#o3.draw_geometries([result])
