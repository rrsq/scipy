""" K-means Clustering and Vector Quantization Module

    Provides routines for k-means clustering, generating code books
    from k-means models, and quantizing vectors by comparing them with
    centroids in a code book.

    The k-means algorithm takes as input the number of clusters to
    generate k and a set of observation vectors to cluster.  It
    returns as its model a set of centroids, one for each of the k
    clusters.  An observation vector is classified with the cluster
    number or centroid index of the centroid closest to it.

    Most variants of k-means try to minimize distortion, which is
    defined as the sum of the distances between each observation and
    its dominating centroid. A vector belongs to a cluster i if it is
    closer to centroid i than the other centroids. Each step of the
    k-means algorithm refines the choices of centroids to reduce
    distortion. The change in distortion is often used as a stopping
    criterion: when the change is lower than a threshold, the k-means
    algorithm is not making progress and terminates.

    Since vector quantization is a natural application for k-means,
    information theory terminology is often used.  The centroid index
    or cluster index is also referred to as a "code" and the table
    mapping codes to centroids and vice versa is often referred as a
    "code book". The result of k-means, a set of centroids, can be
    used to quantize vectors. Quantization aims to find an encoding of
    vectors that reduces the expected distortion.

    For example, suppose we wish to compress a 24-bit color image
    (each pixel is represented by one byte for red, one for blue, and
    one for green) before sending it over the web.  By using a smaller
    8-bit encoding, we can reduce the data to send by two
    thirds. Ideally, the colors for each of the 256 possible 8-bit
    encoding values should be chosen to minimize distortion of the
    color. Running k-means with k=256 generates a code book of 256
    codes, which fills up all possible 8-bit sequences.  Instead of
    sending a 3-byte value for each pixel, the 8-bit centroid index
    (or code word) of the dominating centroid is transmitted. The code
    book is also sent over the wire so each 8-bit code can be
    translated back to a 24-bit pixel value representation. If the
    image of interest was of an ocean, we would expect many 24-bit
    blues to be represented by 8-bit codes. If it was an image of a
    human face, more flesh tone colors would be represented in the
    code book.

    All routines expect the observation vectors to be stored as rows
    in the obs matrix.  Similarly the centroids corresponding to the
    codes are stored as rows of the code_book matrix.  The i'th index
    is the code corresponding to the code_book[i] centroid.

    whiten(obs) --
        Normalize a group of observations so each feature has unit variance.
    vq(obs,code_book) --
        Calculate code book membership of obs.
    kmeans(obs,k_or_guess,iter=20,thresh=1e-5) --
        Train a codebook for mimimum distortion using the k-means algorithm.
    kmeans2
        Similar to kmeans, but with several initialization methods.

"""
__docformat__ = 'restructuredtext'

__all__ = ['whiten', 'vq', 'kmeans', 'kmeans2']

# TODO:
#   - implements high level method for running several times k-means with
#   different initialialization
#   - warning: what happens if different number of clusters ? For now, emit a
#   warning, but it is not great, because I am not sure it really make sense to
#   succeed in this case (maybe an exception is better ?)
import warnings

from numpy.random import randint
from numpy import shape, zeros, sqrt, argmin, minimum, array, \
     newaxis, arange, compress, equal, common_type, single, double, take, \
     std, mean
import numpy as N

class ClusterError(Exception):
    pass

def whiten(obs):
    """ Normalize a group of observations on a per feature basis.

    Before running k-means, it is beneficial to rescale each feature
    dimension of the observation set with whitening. Each feature is
    divided by its standard deviation across all observations to give
    it unit variance.

    :Parameters:
        obs : ndarray
            Each row of the array is an observation.  The
            columns are the features seen during each observation.
            ::

                      #   f0    f1    f2
                obs = [[  1.,   1.,   1.],  #o0
                       [  2.,   2.,   2.],  #o1
                       [  3.,   3.,   3.],  #o2
                       [  4.,   4.,   4.]]) #o3

            XXX perhaps should have an axis variable here.

    :Returns:
        result : ndarray
            Contains the values in obs scaled by the standard devation
            of each column.

    Examples
    --------

    >>> from numpy import array
    >>> from scipy.cluster.vq import whiten
    >>> features  = array([[  1.9,2.3,1.7],
    ...                    [  1.5,2.5,2.2],
    ...                    [  0.8,0.6,1.7,]])
    >>> whiten(features)
    array([[ 3.41250074,  2.20300046,  5.88897275],
           [ 2.69407953,  2.39456571,  7.62102355],
           [ 1.43684242,  0.57469577,  5.88897275]])

    """
    std_dev = std(obs, axis=0)
    return obs / std_dev

def vq(obs, code_book):
    """ Vector Quantization: assign codes from a code book to observations.

    Assigns a code from a code book to each observation. Each
    observation vector in the MxN obs array is compared with the
    centroids in the code book and assigned the code of the closest
    centroid.

    The features in obs should have unit variance, which can be
    acheived by passing them through the whiten function.  The code
    book can be created with the k-means algorithm or a different
    encoding algorithm.

    :Parameters:
        obs : ndarray
            Each row of the NxM array is an observation.  The columns are the
            "features" seen during each observation. The features must be
            whitened first using the whiten function or something equivalent.
        code_book : ndarray.
            The code book is usually generated using the k-means algorithm.
            Each row of the array holds a different code, and the columns are
            the features of the code.

            ::

                            #   f0    f1    f2   f3
                code_book = [[  1.,   2.,   3.,   4.],  #c0
                             [  1.,   2.,   3.,   4.],  #c1
                             [  1.,   2.,   3.,   4.]]) #c2

    :Returns:
        code : ndarray
            A length N array holding the code book index for each observation.
        dist : ndarray
            The distortion (distance) between the observation and its nearest
            code.

    Notes
    -----
    This currently forces 32-bit math precision for speed.  Anyone know
    of a situation where this undermines the accuracy of the algorithm?

    Examples
    --------
    >>> from numpy import array
    >>> from scipy.cluster.vq import vq
    >>> code_book = array([[1.,1.,1.],
    ...                    [2.,2.,2.]])
    >>> features  = array([[  1.9,2.3,1.7],
    ...                    [  1.5,2.5,2.2],
    ...                    [  0.8,0.6,1.7]])
    >>> vq(features,code_book)
    (array([1, 1, 0],'i'), array([ 0.43588989,  0.73484692,  0.83066239]))

    """
    try:
        import _vq
        ct = common_type(obs, code_book)
        c_obs = obs.astype(ct)
        c_code_book = code_book.astype(ct)
        if ct is single:
            results = _vq.vq(c_obs, c_code_book)
        elif ct is double:
            results = _vq.vq(c_obs, c_code_book)
        else:
            results = py_vq(obs, code_book)
    except ImportError:
        results = py_vq(obs, code_book)
    return results

def py_vq(obs, code_book):
    """ Python version of vq algorithm.

    The algorithm computes the euclidian distance between each
    observation and every frame in the code_book.

    :Parameters:
        obs : ndarray
            Expects a rank 2 array. Each row is one observation.
        code_book : ndarray
            Code book to use. Same format than obs. Should have same number of
            features (eg columns) than obs.

    :Note:
        This function is slower than the C version but works for
        all input types.  If the inputs have the wrong types for the
        C versions of the function, this one is called as a last resort.

        It is about 20 times slower than the C version.

    :Returns:
        code : ndarray
            code[i] gives the label of the ith obversation, that its code is
            code_book[code[i]].
        mind_dist : ndarray
            min_dist[i] gives the distance between the ith observation and its
            corresponding code.

    """
    # n = number of observations
    # d = number of features
    if N.ndim(obs) == 1:
        if not N.ndim(obs) == N.ndim(code_book):
            raise ValueError(
                    "Observation and code_book should have the same rank")
        else:
            return _py_vq_1d(obs, code_book)
    else:
        (n, d) = shape(obs)

    # code books and observations should have same number of features and same
    # shape
    if not N.ndim(obs) == N.ndim(code_book):
        raise ValueError("Observation and code_book should have the same rank")
    elif not d == code_book.shape[1]:
        raise ValueError("Code book(%d) and obs(%d) should have the same " \
                         "number of features (eg columns)""" %
                         (code_book.shape[1], d))

    code = zeros(n, dtype=int)
    min_dist = zeros(n)
    for i in range(n):
        dist = N.sum((obs[i] - code_book) ** 2, 1)
        code[i] = argmin(dist)
        min_dist[i] = dist[code[i]]

    return code, sqrt(min_dist)

def _py_vq_1d(obs, code_book):
    """ Python version of vq algorithm for rank 1 only.

    :Parameters:
        obs : ndarray
            Expects a rank 1 array. Each item is one observation.
        code_book : ndarray
            Code book to use. Same format than obs. Should rank 1 too.

    :Returns:
        code : ndarray
            code[i] gives the label of the ith obversation, that its code is
            code_book[code[i]].
        mind_dist : ndarray
            min_dist[i] gives the distance between the ith observation and its
            corresponding code.

    """
    raise RuntimeError("_py_vq_1d buggy, do not use rank 1 arrays for now")
    n = obs.size
    nc = code_book.size
    dist = N.zeros((n, nc))
    for i in range(nc):
        dist[:, i] = N.sum(obs - code_book[i])
    print dist
    code = argmin(dist)
    min_dist = dist[code]

    return code, sqrt(min_dist)

def py_vq2(obs, code_book):
    """2nd Python version of vq algorithm.

    The algorithm simply computes the euclidian distance between each
    observation and every frame in the code_book/

    :Parameters:
        obs : ndarray
            Expect a rank 2 array. Each row is one observation.
        code_book : ndarray
            Code book to use. Same format than obs. Should have same number of
            features (eg columns) than obs.

    :Note:
        This could be faster when number of codebooks is small, but it becomes
        a real memory hog when codebook is large.  It requires NxMxO storage
        where N=number of obs, M = number of features, and O = number of codes.

    :Returns:
        code : ndarray
            code[i] gives the label of the ith obversation, that its code is
            code_book[code[i]].
        mind_dist : ndarray
            min_dist[i] gives the distance between the ith observation and its
            corresponding code.

    """
    d = shape(obs)[1]

    # code books and observations should have same number of features
    if not d == code_book.shape[1]:
        raise ValueError("""
            code book(%d) and obs(%d) should have the same
            number of features (eg columns)""" % (code_book.shape[1], d))

    diff = obs[newaxis, :, :] - code_book[:,newaxis,:]
    dist = sqrt(N.sum(diff * diff, -1))
    code = argmin(dist, 0)
    min_dist = minimum.reduce(dist, 0) #the next line I think is equivalent
                                      #  - and should be faster
    #min_dist = choose(code,dist) # but in practice, didn't seem to make
                                  # much difference.
    return code, min_dist

def _kmeans(obs, guess, thresh=1e-5):
    """ "raw" version of k-means.

    :Returns:
        code_book :
            the lowest distortion codebook found.
        avg_dist :
            the average distance a observation is from a code in the book.
            Lower means the code_book matches the data better.

    :SeeAlso:
        - kmeans : wrapper around k-means

    XXX should have an axis variable here.

    Examples
    --------

    Note: not whitened in this example.

    >>> from numpy import array
    >>> from scipy.cluster.vq import _kmeans
    >>> features  = array([[ 1.9,2.3],
    ...                    [ 1.5,2.5],
    ...                    [ 0.8,0.6],
    ...                    [ 0.4,1.8],
    ...                    [ 1.0,1.0]])
    >>> book = array((features[0],features[2]))
    >>> _kmeans(features,book)
    (array([[ 1.7       ,  2.4       ],
           [ 0.73333333,  1.13333333]]), 0.40563916697728591)

    """

    code_book = array(guess, copy = True)
    nc = code_book.shape[0]
    avg_dist = []
    diff = thresh+1.
    while diff > thresh:
        #compute membership and distances between obs and code_book
        obs_code, distort = vq(obs, code_book)
        avg_dist.append(mean(distort, axis=-1))
        #recalc code_book as centroids of associated obs
        if(diff > thresh):
            has_members = []
            for i in arange(nc):
                cell_members = compress(equal(obs_code, i), obs, 0)
                if cell_members.shape[0] > 0:
                    code_book[i] = mean(cell_members, 0)
                    has_members.append(i)
            #remove code_books that didn't have any members
            code_book = take(code_book, has_members, 0)
        if len(avg_dist) > 1:
            diff = avg_dist[-2] - avg_dist[-1]
    #print avg_dist
    return code_book, avg_dist[-1]

def kmeans(obs, k_or_guess, iter=20, thresh=1e-5):
    """Performs k-means on a set of observations for a specified number of
       iterations. This yields a code book mapping centroids to codes
       and vice versa. The k-means algorithm adjusts the centroids
       until the change in distortion caused by quantizing the
       observation is less than some threshold.

    :Parameters:
        obs : ndarray
            Each row of the M by N array is an observation.  The columns are the
            "features" seen during each observation.  The features must be
            whitened first with the whiten function.
        k_or_guess : int or ndarray
            The number of centroids to generate. One code will be assigned
            to each centroid, and it will be the row index in the code_book
            matrix generated.

            The initial k centroids will be chosen by randomly
            selecting observations from the observation
            matrix. Alternatively, passing a k by N array specifies
            the initial values of the k means.

        iter : int
            The number of times to run k-means, returning the codebook
            with the lowest distortion. This argument is ignored if
            initial mean values are specified with an array for the
            k_or_guess paramter. This parameter does not represent the
            number of iterations of the k-means algorithm.

        thresh : float
            Terminates the k-means algorithm if the change in
            distortion since the last k-means iteration is less than
            thresh.

    :Returns:
        codebook : ndarray
            A k by N array of k centroids. The i'th centroid
            codebook[i] is represented with the code i. The centroids
            and codes generated represent the lowest distortion seen,
            not necessarily the global minimum distortion.

        distortion : float
           The distortion between the observations passed and the
           centroids generated.

    :SeeAlso:
        - kmeans2: similar function, but with more options for initialization,
          and returns label of each observation
        - whiten: must be called prior to passing an observation matrix
          to kmeans.

    Examples
    --------

    >>> from numpy import array
    >>> from scipy.cluster.vq import vq, kmeans, whiten
    >>> features  = array([[ 1.9,2.3],
    ...                    [ 1.5,2.5],
    ...                    [ 0.8,0.6],
    ...                    [ 0.4,1.8],
    ...                    [ 0.1,0.1],
    ...                    [ 0.2,1.8],
    ...                    [ 2.0,0.5],
    ...                    [ 0.3,1.5],
    ...                    [ 1.0,1.0]])
    >>> whitened = whiten(features)
    >>> book = array((whitened[0],whitened[2]))
    >>> kmeans(whitened,book)
    (array([[ 2.3110306 ,  2.86287398],
           [ 0.93218041,  1.24398691]]), 0.85684700941625547)

    >>> from numpy import random
    >>> random.seed((1000,2000))
    >>> codes = 3
    >>> kmeans(whitened,codes)
    (array([[ 2.3110306 ,  2.86287398],
           [ 1.32544402,  0.65607529],
           [ 0.40782893,  2.02786907]]), 0.5196582527686241)

    """
    if int(iter) < 1:
        raise ValueError, 'iter must be >= to 1.'
    if type(k_or_guess) == type(array([])):
        guess = k_or_guess
        result = _kmeans(obs, guess, thresh = thresh)
    else:
        #initialize best distance value to a large value
        best_dist = 100000
        No = obs.shape[0]
        k = k_or_guess
        #print 'kmeans iter: ',
        for i in range(iter):
            #the intial code book is randomly selected from observations
            guess = take(obs, randint(0, No, k), 0)
            book, dist = _kmeans(obs, guess, thresh = thresh)
            if dist < best_dist:
                best_book = book
                best_dist = dist
        result = best_book, best_dist
    return result

def _kpoints(data, k):
    """Pick k points at random in data (one row = one observation).

    This is done by taking the k first values of a random permutation of 1..N
    where N is the number of observation.

    :Parameters:
        data : ndarray
            Expect a rank 1 or 2 array. Rank 1 are assumed to describe one
            dimensional data, rank 2 multidimensional data, in which case one
            row is one observation.
        k : int
            Number of samples to generate.

    """
    if data.ndim > 1:
        n = data.shape[0]
    else:
        n = data.size

    p = N.random.permutation(n)
    x = data[p[:k], :].copy()

    return x

def _krandinit(data, k):
    """Returns k samples of a random variable which parameters depend on data.

    More precisely, it returns k observations sampled from a Gaussian random
    variable which mean and covariances are the one estimated from data.

    :Parameters:
        data : ndarray
            Expect a rank 1 or 2 array. Rank 1 are assumed to describe one
            dimensional data, rank 2 multidimensional data, in which case one
            row is one observation.
        k : int
            Number of samples to generate.

    """
    def init_rank1(data):
        mu  = N.mean(data)
        cov = N.cov(data)
        x = N.random.randn(k)
        x *= N.sqrt(cov)
        x += mu
        return x
    def init_rankn(data):
        mu  = N.mean(data, 0)
        cov = N.atleast_2d(N.cov(data, rowvar = 0))

        # k rows, d cols (one row = one obs)
        # Generate k sample of a random variable ~ Gaussian(mu, cov)
        x = N.random.randn(k, mu.size)
        x = N.dot(x, N.linalg.cholesky(cov).T) + mu
        return x

    nd = N.ndim(data)
    if nd == 1:
        return init_rank1(data)
    else:
        return init_rankn(data)

_valid_init_meth = {'random': _krandinit, 'points': _kpoints}

def _missing_warn():
    """Print a warning when called."""
    warnings.warn("One of the clusters is empty. "
                 "Re-run kmean with a different initialization.")

def _missing_raise():
    """raise a ClusterError when called."""
    raise ClusterError, "One of the clusters is empty. "\
                        "Re-run kmean with a different initialization."

_valid_miss_meth = {'warn': _missing_warn, 'raise': _missing_raise}

def kmeans2(data, k, iter = 10, thresh = 1e-5, minit = 'random',
        missing = 'warn'):
    """Classify a set of observations into k clusters using the k-means
       algorithm.

    The algorithm attempts to minimize the Euclidian distance between
    observations and centroids. Several initialization methods are
    included.

    :Parameters:
        data : ndarray
            A M by N array of M observations in N dimensions or a length
            M array of M one-dimensional observations.
        k : int or ndarray
            The number of clusters to form as well as the number of
            centroids to generate. If minit initialization string is
            'matrix', or if a ndarray is given instead, it is
            interpreted as initial cluster to use instead.
        niter : int
            Number of iterations of k-means to run. Note that this
            differs in meaning from the iters parameter to the kmeans
            function.
        thresh : float
            (not used yet).
        minit : string
            Method for initialization. Available methods are 'random',
            'points', 'uniform', and 'matrix':

            'random': generate k centroids from a Gaussian with mean and
            variance estimated from the data.

            'points': choose k observations (rows) at random from data for
            the initial centroids.

            'uniform': generate k observations from the data from a uniform
            distribution defined by the data set (unsupported).

            'matrix': interpret the k parameter as a k by M (or length k
            array for one-dimensional data) array of initial centroids.

    :Returns:
        centroid : ndarray
            A k by N array of centroids found at the last iteration of
            k-means.
        label : ndarray
            label[i] is the code or index of the centroid the
            i'th observation is closest to.
    """
    if missing not in _valid_miss_meth.keys():
        raise ValueError("Unkown missing method: %s" % str(missing))
    # If data is rank 1, then we have 1 dimension problem.
    nd  = N.ndim(data)
    if nd == 1:
        d = 1
        #raise ValueError("Input of rank 1 not supported yet")
    elif nd == 2:
        d = data.shape[1]
    else:
        raise ValueError("Input of rank > 2 not supported")

    # If k is not a single value, then it should be compatible with data's
    # shape
    if N.size(k) > 1 or minit == 'matrix':
        if not nd == N.ndim(k):
            raise ValueError("k is not an int and has not same rank than data")
        if d == 1:
            nc = len(k)
        else:
            (nc, dc) = k.shape
            if not dc == d:
                raise ValueError("k is not an int and has not same rank than\
                        data")
        clusters = k.copy()
    else:
        nc = int(k)
        if not nc == k:
            warnings.warn("k was not an integer, was converted.")
        try:
            init = _valid_init_meth[minit]
        except KeyError:
            raise ValueError("unknown init method %s" % str(minit))
        clusters = init(data, k)

    assert not iter == 0
    return _kmeans2(data, clusters, iter, nc, _valid_miss_meth[missing])

def _kmeans2(data, code, niter, nc, missing):
    """ "raw" version of kmeans2. Do not use directly.

    Run k-means with a given initial codebook.  """
    for i in range(niter):
        # Compute the nearest neighbour for each obs
        # using the current code book
        label = vq(data, code)[0]
        # Update the code by computing centroids using the new code book
        for j in range(nc):
            mbs = N.where(label==j)
            if mbs[0].size > 0:
                code[j] = N.mean(data[mbs], axis=0)
            else:
                missing()

    return code, label

if __name__  == '__main__':
    pass
    #import _vq
    #a = N.random.randn(4, 2)
    #b = N.random.randn(2, 2)

    #print _vq.vq(a, b)
    #print _vq.vq(N.array([[1], [2], [3], [4], [5], [6.]]),
    #        N.array([[2.], [5.]]))
    #print _vq.vq(N.array([1, 2, 3, 4, 5, 6.]), N.array([2., 5.]))
    #_vq.vq(a.astype(N.float32), b.astype(N.float32))
    #_vq.vq(a, b.astype(N.float32))
    #_vq.vq([0], b)
